#!/usr/bin/env python3
"""
etl_lemans.py
=============
Proces ETL zasilający bazę SQLite LeMans24h danymi z Kaggle.
Zastępuje istniejące rekordy pełnymi, ujednoliconymi danymi (1923-2023).
"""

from __future__ import annotations

import argparse
import csv
import itertools
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

RESULTS_CHUNKSIZE = 5000

# Współrzędne bazowe toru Le Mans (WGS84 / EPSG:4326)
DEFAULT_LE_MANS_LAT = 47.9542
DEFAULT_LE_MANS_LON = 0.2078

NATIONALITY_MAP = {
    "AUS": "Australia", "AUT": "Austria", "BEL": "Belgium", "BRA": "Brazil",
    "CAN": "Canada", "CHE": "Switzerland", "SUI": "Switzerland",
    "CHN": "China", "CZE": "Czech Republic", "DNK": "Denmark", "DEN": "Denmark",
    "ESP": "Spain", "EST": "Estonia", "FIN": "Finland", "FRA": "France",
    "DEU": "Germany", "GER": "Germany", "GBR": "Great Britain", "GB": "Great Britain",
    "GRC": "Greece", "GRE": "Greece", "HKG": "Hong Kong", "HUN": "Hungary",
    "IDN": "Indonesia", "IND": "India", "IRL": "Ireland", "ISR": "Israel",
    "ITA": "Italy", "JPN": "Japan", "KOR": "South Korea", "LUX": "Luxembourg",
    "MCO": "Monaco", "MON": "Monaco", "MEX": "Mexico", "MYS": "Malaysia", "MAS": "Malaysia",
    "NLD": "Netherlands", "NED": "Netherlands", "NOR": "Norway",
    "NZL": "New Zealand", "POL": "Poland", "PRT": "Portugal", "POR": "Portugal",
    "ROU": "Romania", "ROM": "Romania", "RUS": "Russia", "SGP": "Singapore",
    "SIN": "Singapore", "SVK": "Slovakia", "SVN": "Slovenia", "SLO": "Slovenia",
    "SWE": "Sweden", "THA": "Thailand", "TUR": "Turkey", "UKR": "Ukraine",
    "URY": "Uruguay", "URU": "Uruguay", "USA": "USA", "VEN": "Venezuela",
    "ZAF": "South Africa", "RSA": "South Africa", "ARG": "Argentina",
    "COL": "Colombia", "CHL": "Chile", "CHI": "Chile", "IRN": "Iran",
    "LVA": "Latvia", "LTU": "Lithuania", "HRV": "Croatia", "SRB": "Serbia",
    "BGR": "Bulgaria", "BUL": "Bulgaria",
}

# Słownik kanonicznych producentów podwozi (wyczyszczony z zespołów takich jak Joest, AMR)
CANONICAL_MAKES = [
    "Alfa Romeo", "Alpine-Renault", "Alpine", "Aston Martin", "Audi",
    "Austin-Healey", "Auto Union", "Bentley", "BMW", "Bugatti", "Cadillac",
    "Callaway", "Caterham", "Chaparrall", "Chapparal", "Chevron", "Chrysler",
    "Chenard-Walcker", "Chevrolet", "Cisitalia", "Cooper", "Courage-Nissan",
    "Courage-Porsche", "Courage", "Cunningham", "Dallara", "De Cadenet",
    "De Tomaso", "Delage", "Delahaye", "Deutsch-Bonnet", "DB", "Dodge",
    "Dome", "Elva", "EMKA", "Epsilon", "Ferrari", "Fiat", "Ford",
    "Frazer Nash", "Ginetta-Zytek", "Ginetta", "Glickenhaus", "Gordini",
    "Healey", "Hino", "Hispano-Suiza", "Honda", "Howmet", "Jaguar",
    "Kool Green", "Kremer", "KTM", "Lagonda", "Lamborghini", "Lancia",
    "Ligier", "Lister", "Lola-Aston Martin", "Lola-Judd", "Lola", "Lotus",
    "Marcos", "Maserati", "Matra-Simca", "Matra", "Mazda", "McLaren",
    "Mercedes-Benz", "Mercedes", "Mirage-Ford", "Mirage", "Morgan",
    "Mosler", "Nardi", "Nissan", "Norma", "OM", "Onroak Automotive",
    "ORECA", "OSCA", "Panoz", "Panhard", "Pescarolo", "Peugeot",
    "Pilbeam", "Porsche", "Praga", "Radical", "Rebellion", "Renault",
    "Riley & Scott", "Riley", "Rondeau", "Rover-BRM", "Rover", "Sauber-Mercedes",
    "Sauber", "SARD", "Shelby", "Spice-Ferrari", "Spice", "Spyker",
    "Stanguellini", "Stutz", "Sunbeam", "Talbot-Lago", "Talbot", "Tiga",
    "Tauro", "Toyota", "Triumph", "TVR", "Vanwall", "Veritas", "Viper",
    "Welter Racing", "WR", "WM-Peugeot", "WM", "Zytek"
]

# Mapowanie wariantów zapisu i literówek na nazwy kanoniczne
MAKE_ALIASES = {
    "oreca": "ORECA",
    "wm": "WM",
    "wr": "WR",
    "db": "DB",
    "chenard et walcker": "Chenard-Walcker",
    "chenard and walcker": "Chenard-Walcker",
    "chenard & walcker": "Chenard-Walcker",
    "riley and scott": "Riley & Scott",
    "riley & scott": "Riley & Scott",
    "alfa-romeo": "Alfa Romeo",
    "aston-martin": "Aston Martin",
    "mercedes benz": "Mercedes-Benz",
    "corvette": "Chevrolet",
    "dodge viper": "Dodge",
    "chrysler viper": "Chrysler",
    "matra simca": "Matra-Simca",
    "alpine renault": "Alpine-Renault",
}

NAME_PARTICLES = {
    "van", "von", "der", "den", "de", "du", "da", "des", "di", "la", "le",
    "el", "al", "bin", "ibn", "af", "av", "dos", "das",
}
NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}


def setup_logging(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("lemans_etl")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def safe_str(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def split_pipe(value: str) -> list[str]:
    clean = safe_str(value)
    if not clean:
        return []
    return [part.strip() for part in clean.split("|") if part.strip()]


def split_driver_name(full_name: str) -> tuple[str | None, str]:
    tokens = full_name.split()
    if len(tokens) <= 1:
        return None, full_name

    if tokens[-1].lower().rstrip(".") in NAME_SUFFIXES and len(tokens) >= 3:
        last_name = " ".join(tokens[-2:])
        first_tokens = tokens[:-2]
    else:
        last_name = tokens[-1]
        first_tokens = tokens[:-1]

    while first_tokens and first_tokens[-1].lower() in NAME_PARTICLES:
        last_name = first_tokens[-1] + " " + last_name
        first_tokens = first_tokens[:-1]

    first_name = " ".join(first_tokens) if first_tokens else None
    return first_name, last_name


def clean_position(raw: object) -> tuple[int | None, str]:
    clean = safe_str(raw)
    if clean.isdigit() and int(clean) > 0:
        return int(clean), "Finished"
    return None, (clean.upper() if clean else "Unknown")


def parse_car_number(raw: object) -> int | None:
    clean = safe_str(raw)
    match = re.match(r"^(\d+)", clean)
    return int(match.group(1)) if match else None


def map_nationality(code: str) -> str:
    code = safe_str(code).upper()
    return NATIONALITY_MAP.get(code, code)


class MakeMatcher:
    def __init__(self, canonical_makes: list[str], aliases: dict[str, str]):
        self.aliases = {k.lower(): v for k, v in aliases.items()}
        # Sortowanie według długości malejąco, aby zapobiec fałszywemu dopasowaniu prefiksów
        sorted_makes = sorted(canonical_makes, key=len, reverse=True)
        patterns = [re.escape(m) for m in sorted_makes]
        self.regex = re.compile(rf"^({'|'.join(patterns)})(?:[\s\-_/]+(.*)|$)", re.IGNORECASE)

    def match(self, chassis_raw: object) -> tuple[str, str, bool]:
        chassis = safe_str(chassis_raw)
        if not chassis:
            return "Unknown", "Unknown", False

        # Sprawdzenie dedykowanych aliasów
        ch_lower = chassis.lower()
        for alias, canonical in self.aliases.items():
            if ch_lower == alias or ch_lower.startswith(alias + " "):
                remainder = chassis[len(alias):].strip(" -_/")
                return canonical, remainder or "Unknown", True

        # Dopasowanie regex case-insensitive
        match = self.regex.match(chassis)
        if match:
            raw_make = match.group(1)
            remainder = match.group(2) or "Unknown"
            # Zwracamy znormalizowany zapis kanoniczny
            matched_make = next(m for m in CANONICAL_MAKES if m.lower() == raw_make.lower())
            return matched_make, remainder.strip(), True

        # Wycofanie (fallback) - podział na pierwszy token
        parts = re.split(r"[\s\-_/]+", chassis, maxsplit=1)
        fallback_make = parts[0]
        fallback_model = parts[1] if len(parts) > 1 else "Unknown"
        return fallback_make, fallback_model, False


SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS Teams (
    TeamID INTEGER PRIMARY KEY AUTOINCREMENT,
    TeamName TEXT NOT NULL,
    Country TEXT,
    CountryCode TEXT,
    EstablishedYear INTEGER
);

CREATE TABLE IF NOT EXISTS Cars (
    CarID INTEGER PRIMARY KEY AUTOINCREMENT,
    Make TEXT NOT NULL,
    Model TEXT,
    EngineType TEXT
);

CREATE TABLE IF NOT EXISTS Drivers (
    DriverID INTEGER PRIMARY KEY AUTOINCREMENT,
    FirstName TEXT,
    LastName TEXT,
    Nationality TEXT,
    CountryCode TEXT
);

CREATE TABLE IF NOT EXISTS Circuits (
    CircuitID INTEGER PRIMARY KEY AUTOINCREMENT,
    Name TEXT NOT NULL,
    SinceYear INTEGER,
    LengthKm REAL,
    Changes TEXT,
    Latitude REAL DEFAULT 47.9542,
    Longitude REAL DEFAULT 0.2078,
    SRID INTEGER DEFAULT 4326,
    GeometryWKT TEXT,
    UNIQUE (Name, SinceYear)
);

CREATE TABLE IF NOT EXISTS Races (
    RaceID INTEGER PRIMARY KEY,
    Year INTEGER NOT NULL,
    StartDate DATE,
    EndDate DATE,
    CircuitID INTEGER REFERENCES Circuits(CircuitID),
    DistanceKm REAL,
    Cancelled INTEGER NOT NULL DEFAULT 0,
    CancellationReason TEXT
);

CREATE TABLE IF NOT EXISTS RaceEntries (
    EntryID INTEGER PRIMARY KEY AUTOINCREMENT,
    RaceID INTEGER NOT NULL,
    TeamID INTEGER NOT NULL,
    CarID INTEGER NOT NULL,
    CarNumber INTEGER NOT NULL,
    Class TEXT,
    UNIQUE (RaceID, CarNumber),
    FOREIGN KEY (TeamID) REFERENCES Teams(TeamID) ON DELETE RESTRICT,
    FOREIGN KEY (CarID) REFERENCES Cars(CarID) ON DELETE RESTRICT,
    FOREIGN KEY (RaceID) REFERENCES Races(RaceID) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS RaceResults (
    ResultID INTEGER PRIMARY KEY AUTOINCREMENT,
    EntryID INTEGER,
    FinishingPosition INTEGER,
    Status TEXT,
    CHECK (FinishingPosition > 0 OR FinishingPosition IS NULL),
    FOREIGN KEY (EntryID) REFERENCES RaceEntries(EntryID) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS DriverAssignments (
    AssignmentID INTEGER PRIMARY KEY AUTOINCREMENT,
    EntryID INTEGER,
    DriverID INTEGER,
    FOREIGN KEY (EntryID) REFERENCES RaceEntries(EntryID) ON DELETE RESTRICT,
    FOREIGN KEY (DriverID) REFERENCES Drivers(DriverID) ON DELETE RESTRICT
);
"""

def reset_and_migrate_db(conn: sqlite3.Connection, clean_start: bool, logger: logging.Logger) -> None:
    cur = conn.cursor()

    if clean_start:
        logger.warning("Tryb --clean-start aktywny: usuwanie i odtwarzanie schematu bazy...")
        # Wyłączamy sprawdzanie kluczy obcych na czas bezpiecznego usuwania tabel
        cur.execute("PRAGMA foreign_keys = OFF")

        tables_to_purge = [
            "DriverAssignments", "RaceResults", "RaceEntries",
            "Races", "Circuits", "Cars", "Teams", "Drivers"
        ]
        for tbl in tables_to_purge:
            cur.execute(f"DROP TABLE IF EXISTS {tbl}")

        cur.execute("PRAGMA foreign_keys = ON")
        conn.commit()

    # Tworzymy kompletny, czysty zestaw tabel (jeśli nie istnieją)
    cur.executescript(SCHEMA_DDL)
    conn.commit()
    logger.info("Schemat bazy danych zweryfikowany i gotowy do zasilenia.")

    # Schemat tabeli Circuits z rozszerzeniem geoprzestrzennym
    cur.execute(
        """CREATE TABLE IF NOT EXISTS Circuits (
               CircuitID INTEGER PRIMARY KEY AUTOINCREMENT,
               Name TEXT NOT NULL,
               SinceYear INTEGER,
               LengthKm REAL,
               Changes TEXT,
               Latitude REAL DEFAULT 47.9542,
               Longitude REAL DEFAULT 0.2078,
               SRID INTEGER DEFAULT 4326,
               GeometryWKT TEXT,
               UNIQUE (Name, SinceYear)
           )"""
    )

    column_checks = [
        ("Races", "CircuitID", "INTEGER REFERENCES Circuits(CircuitID)"),
        ("Races", "DistanceKm", "REAL"),
        ("Races", "Cancelled", "INTEGER NOT NULL DEFAULT 0"),
        ("Races", "CancellationReason", "TEXT"),
        ("RaceEntries", "Class", "TEXT"),
        ("Teams", "CountryCode", "TEXT"),
        ("Drivers", "CountryCode", "TEXT"),
    ]

    for table, col, coltype in column_checks:
        cur.execute(f"PRAGMA table_info({table})")
        existing_cols = [row[1] for row in cur.fetchall()]
        if col not in existing_cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
            logger.info("Dodano kolumnę do schematu: %s.%s", table, col)
    conn.commit()


@dataclass
class Caches:
    teams: dict[str, int] = field(default_factory=dict)
    cars: dict[tuple, int] = field(default_factory=dict)
    drivers: dict[tuple, int] = field(default_factory=dict)
    circuits: dict[tuple, int] = field(default_factory=dict)
    race_years: dict[int, int] = field(default_factory=dict)


def load_caches(conn: sqlite3.Connection) -> Caches:
    c = Caches()
    cur = conn.cursor()
    for team_id, name in cur.execute("SELECT TeamID, TeamName FROM Teams"):
        c.teams[name.strip().lower()] = team_id
    for car_id, make, model, engine in cur.execute("SELECT CarID, Make, Model, EngineType FROM Cars"):
        c.cars[(make, model, engine)] = car_id
    for drv_id, first, last in cur.execute("SELECT DriverID, FirstName, LastName FROM Drivers"):
        key = ((first or "").strip().lower(), (last or "").strip().lower())
        c.drivers[key] = drv_id
    for race_id, year in cur.execute("SELECT RaceID, Year FROM Races"):
        c.race_years[year] = race_id
    for circuit_id, name, since_year in cur.execute("SELECT CircuitID, Name, SinceYear FROM Circuits"):
        c.circuits[(name, since_year)] = circuit_id
    return c


def get_or_create_team(cur: sqlite3.Cursor, cache: Caches, name: str, country_code: str) -> tuple[int, bool, str]:
    name = safe_str(name) or "Unknown Team"
    key = name.lower()
    if key in cache.teams:
        return cache.teams[key], False, key
    iso_code = safe_str(country_code).upper() or None
    cur.execute(
        "INSERT INTO Teams (TeamName, Country, CountryCode, EstablishedYear) VALUES (?, ?, ?, NULL)",
        (name, map_nationality(country_code) if country_code else None, iso_code),
    )
    new_id = cur.lastrowid
    cache.teams[key] = new_id
    return new_id, True, key


def get_or_create_car(cur: sqlite3.Cursor, cache: Caches, make: str, model: str, engine: str) -> tuple[int, bool, tuple]:
    engine = safe_str(engine) or None
    key = (make, model, engine)
    if key in cache.cars:
        return cache.cars[key], False, key
    cur.execute(
        "INSERT INTO Cars (Make, Model, EngineType) VALUES (?, ?, ?)",
        (make, model, engine),
    )
    new_id = cur.lastrowid
    cache.cars[key] = new_id
    return new_id, True, key


def get_or_create_driver(cur: sqlite3.Cursor, cache: Caches, full_name: str, nat_code: str) -> tuple[int, bool, tuple]:
    first, last = split_driver_name(full_name)
    key = ((first or "").lower(), last.lower())
    if key in cache.drivers:
        return cache.drivers[key], False, key
    iso_code = safe_str(nat_code).upper() or None
    cur.execute(
        "INSERT INTO Drivers (FirstName, LastName, Nationality, CountryCode) VALUES (?, ?, ?, ?)",
        (first, last, map_nationality(nat_code) if nat_code else None, iso_code),
    )
    new_id = cur.lastrowid
    cache.drivers[key] = new_id
    return new_id, True, key


def import_circuits(conn: sqlite3.Connection, cache: Caches, path: Path, logger: logging.Logger) -> dict[int, int]:
    df = pd.read_csv(path, sep=";", dtype=str)
    position_to_id: dict[int, int] = {}
    cur = conn.cursor()
    for i, row in enumerate(df.itertuples(index=False), start=1):
        since_year = pd.to_datetime(row.Since).year
        length_km = float(row.Length_km) if safe_str(row.Length_km) else None
        key = (row.Name, since_year)
        if key in cache.circuits:
            circuit_id = cache.circuits[key]
        else:
            cur.execute(
                """INSERT INTO Circuits (Name, SinceYear, LengthKm, Changes, Latitude, Longitude)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (row.Name, since_year, length_km, row.Changes, DEFAULT_LE_MANS_LAT, DEFAULT_LE_MANS_LON),
            )
            circuit_id = cur.lastrowid
            cache.circuits[key] = circuit_id
        position_to_id[i] = circuit_id
    conn.commit()
    logger.info("Zaktualizowano konfiguracje toru Circuits z %s", path.name)
    return position_to_id


def import_races(conn: sqlite3.Connection, cache: Caches, path: Path,
                 circuit_map: dict[int, int], logger: logging.Logger) -> None:
    df = pd.read_csv(path, sep=";", dtype=str)
    cur = conn.cursor()
    inserted = 0
    for row in df.itertuples(index=False):
        event_date = pd.to_datetime(row.Event_date)
        year = event_date.year
        race_id = int(row.Id)
        start_date = event_date.date().isoformat()
        end_date = (event_date + pd.Timedelta(days=1)).date().isoformat()
        circuit_id = circuit_map.get(int(row.Circuit_Id))
        distance_km = float(row.Distance_km) if safe_str(row.Distance_km) else None
        cancelled = int(row.Cancelled)
        cancellation_reason = safe_str(row.Cancellation_reason) or None

        cur.execute(
            """INSERT INTO Races
               (RaceID, Year, StartDate, EndDate, CircuitID, DistanceKm, Cancelled, CancellationReason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (race_id, year, start_date, end_date, circuit_id, distance_km, cancelled, cancellation_reason),
        )
        cache.race_years[year] = race_id
        inserted += 1
    conn.commit()
    logger.info("Races: zaimportowano %d edycji wyścigu.", inserted)


def import_results(conn: sqlite3.Connection, cache: Caches, path: Path,
                   matcher: MakeMatcher, logger: logging.Logger,
                   unmatched_makes_path: Path, chunksize: int) -> None:
    cur = conn.cursor()
    unmatched_rows: list[dict] = []
    total_entries = 0
    failed_entries = 0

    for chunk in pd.read_csv(path, sep=";", dtype=str, chunksize=chunksize):
        for row in chunk.itertuples(index=False):
            year_raw = safe_str(getattr(row, "Year", None))
            if not year_raw.isdigit():
                continue
            year = int(year_raw)
            race_id = cache.race_years.get(year)
            if race_id is None:
                continue

            car_number = parse_car_number(getattr(row, "No", None))
            if car_number is None:
                failed_entries += 1
                continue

            chassis_raw = getattr(row, "Chassis", None)
            make, model, matched = matcher.match(chassis_raw)
            if not matched:
                unmatched_rows.append({
                    "Year": year,
                    "Chassis": safe_str(chassis_raw),
                    "Guessed_Make": make,
                    "Guessed_Model": model,
                })

            cur.execute("SAVEPOINT row_sp")
            new_cache_entries: list[tuple[dict, object]] = []
            try:
                team_id, team_new, team_key = get_or_create_team(
                    cur, cache, getattr(row, "Team", None), getattr(row, "TeamCtry", None)
                )
                if team_new:
                    new_cache_entries.append((cache.teams, team_key))

                car_id, car_new, car_key = get_or_create_car(
                    cur, cache, make, model, getattr(row, "Engine", None)
                )
                if car_new:
                    new_cache_entries.append((cache.cars, car_key))

                car_class = safe_str(getattr(row, "Class", None)) or None

                cur.execute(
                    """INSERT INTO RaceEntries (RaceID, TeamID, CarID, CarNumber, Class)
                       VALUES (?, ?, ?, ?, ?)""",
                    (race_id, team_id, car_id, car_number, car_class),
                )
                entry_id = cur.lastrowid

                position, status = clean_position(getattr(row, "Pos", None))
                cur.execute(
                    "INSERT INTO RaceResults (EntryID, FinishingPosition, Status) VALUES (?, ?, ?)",
                    (entry_id, position, status),
                )

                drivers = split_pipe(getattr(row, "Drivers", None))
                nationalities = split_pipe(getattr(row, "DrCtry", None))
                for driver_name, nat_code in itertools.zip_longest(drivers, nationalities, fillvalue=""):
                    if not driver_name:
                        continue
                    driver_id, drv_new, drv_key = get_or_create_driver(cur, cache, driver_name, nat_code)
                    if drv_new:
                        new_cache_entries.append((cache.drivers, drv_key))
                    cur.execute(
                        "INSERT INTO DriverAssignments (EntryID, DriverID) VALUES (?, ?)",
                        (entry_id, driver_id),
                    )

                cur.execute("RELEASE row_sp")
                total_entries += 1

            except sqlite3.IntegrityError:
                cur.execute("ROLLBACK TO row_sp")
                cur.execute("RELEASE row_sp")
                for cache_dict, cache_key in new_cache_entries:
                    cache_dict.pop(cache_key, None)
                failed_entries += 1

    conn.commit()

    if unmatched_rows:
        with open(unmatched_makes_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["Year", "Chassis", "Guessed_Make", "Guessed_Model"])
            writer.writeheader()
            writer.writerows(unmatched_rows)
        logger.info("Zapisano %d nierozpoznanych rekordów do: %s", len(unmatched_rows), unmatched_makes_path)

    logger.info("Zaimportowano zgłoszeń: %d (odrzuconych: %d)", total_entries, failed_entries)


def run_etl(db_path: Path, circuits_path: Path, races_path: Path, results_path: Path,
            clean_start: bool, chunksize: int, out_dir: Path) -> None:
    logger = setup_logging(out_dir / "etl_log.txt")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    reset_and_migrate_db(conn, clean_start=clean_start, logger=logger)
    cache = load_caches(conn)

    matcher = MakeMatcher(CANONICAL_MAKES, MAKE_ALIASES)
    circuit_map = import_circuits(conn, cache, circuits_path, logger)
    import_races(conn, cache, races_path, circuit_map, logger)
    import_results(
        conn, cache, results_path, matcher, logger,
        unmatched_makes_path=out_dir / "unmatched_makes.csv", chunksize=chunksize,
    )

    conn.close()
    logger.info("Proces ETL zakończony pomyślnie.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ETL Le Mans 24h z obsługą czystego startu i geoprzestrzeni")
    parser.add_argument("--db", default="LeMans24h.db")
    parser.add_argument("--circuits", default="circuits.csv")
    parser.add_argument("--races", default="races.csv")
    parser.add_argument("--results", default="results_in.csv")
    parser.add_argument("--clean-start", action="store_true", default=True,
                        help="Wyczyść tabele przed importem (nadpisanie starych 22 edycji danymi z Kaggle)")
    parser.add_argument("--chunksize", type=int, default=RESULTS_CHUNKSIZE)
    parser.add_argument("--out-dir", default=".")
    args = parser.parse_args()

    run_etl(
        db_path=Path(args.db),
        circuits_path=Path(args.circuits),
        races_path=Path(args.races),
        results_path=Path(args.results),
        clean_start=args.clean_start,
        chunksize=args.chunksize,
        out_dir=Path(args.out_dir),
    )