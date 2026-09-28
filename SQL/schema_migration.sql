-- ============================================================================
-- schema_migration.sql
-- Rozszerza istniejący, znormalizowany schemat (7 tabel) o encje i atrybuty,
-- które są obecne w źródłowych plikach Kaggle, ale nie mają dziś odpowiednika
-- w bazie:
--
--   1) circuits.csv opisuje ODDZIELNĄ ENCJĘ (tor / konfigurację toru w danym
--      okresie) -> potrzebna jest osobna tabela Circuits, a nie kolumna
--      w Races (jeden tor obsługuje wiele edycji wyścigu = relacja 1:N).
--   2) races.csv niesie atrybuty wyścigu, których dziś nie ma gdzie zapisać:
--      odniesienie do toru, dystans, informację o odwołaniu wyścigu i powód.
--   3) results_in.csv niesie klasę (kategorię) zgłoszenia (np. LMP1, GTE Pro),
--      która jest atrybutem KONKRETNEGO zgłoszenia (RaceEntries), a nie
--      samego modelu samochodu (Cars) — bo ten sam model auta mógł w różnych
--      latach/wpisach startować w różnych klasach.
--
-- Skrypt jest idempotentny na poziomie logicznym (ETL w Pythonie sprawdza
-- PRAGMA table_info przed wykonaniem ALTER, więc można go uruchamiać
-- wielokrotnie bez błędu "duplicate column"). Ten plik .sql to wersja
-- "goła" do ręcznego uruchomienia raz, np. w DB Browser for SQLite.
-- ============================================================================

CREATE TABLE IF NOT EXISTS Circuits (
    CircuitID   INTEGER PRIMARY KEY AUTOINCREMENT,
    Name        TEXT NOT NULL,
    SinceYear   INTEGER,      -- rok, od którego obowiązywała dana konfiguracja toru
    LengthKm    REAL,
    Changes     TEXT,         -- opis zmian względem poprzedniej konfiguracji
    UNIQUE (Name, SinceYear)
);

ALTER TABLE Races ADD COLUMN CircuitID INTEGER REFERENCES Circuits(CircuitID);
ALTER TABLE Races ADD COLUMN DistanceKm REAL;
ALTER TABLE Races ADD COLUMN Cancelled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE Races ADD COLUMN CancellationReason TEXT;

ALTER TABLE RaceEntries ADD COLUMN Class TEXT;
