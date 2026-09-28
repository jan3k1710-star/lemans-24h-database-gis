"""
gis_lemans_analysis.py
======================
Most danych geoprzestrzennych między bazą SQLite LeMans24h.db a QGIS:
1. Zasilenie bazy SQLite tabelą odcinków 3D (CircuitTrackSegments) oraz linią WKT.
2. Możliwość generowania danych prosto z bazy SQLite (nawet bez pliku GPX).
3. Generowanie warstwy płynnego gradientu wysokości dla QGIS (Linia interpolowana).
"""

import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from shapely.geometry import LineString
from shapely import wkt

GPX_PATH = Path("LeMans24hCircuit.gpx")
DB_PATH = Path("LeMans24h.db")
OUTPUT_GPKG = Path("lemans_geodata.gpkg")


def parse_gpx_to_segments(gpx_path: Path):
    """Przetwarza plik GPX na punkty i 279 ciągłych mikro-odcinków toru."""
    tree = ET.parse(gpx_path)
    root = tree.getroot()
    ns = {"gpx": "http://www.topografix.com/GPX/1/1"}

    coords_2d = []
    points = []

    for trkpt in root.findall(".//gpx:trkpt", ns):
        lat = float(trkpt.attrib["lat"])
        lon = float(trkpt.attrib["lon"])
        ele = float(trkpt.find("gpx:ele", ns).text) if trkpt.find("gpx:ele", ns) is not None else 0.0
        coords_2d.append((lon, lat))
        points.append({"lon": lon, "lat": lat, "ele": ele})

    full_line = LineString(coords_2d)

    segments = []
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i + 1]
        seg_geom = LineString([(p1["lon"], p1["lat"]), (p2["lon"], p2["lat"])])
        segments.append({
            "seq_id": i,
            "ele_start": p1["ele"],
            "ele_end": p2["ele"],
            "ele_avg": round((p1["ele"] + p2["ele"]) / 2.0, 2),
            "geometry": seg_geom
        })

    return full_line, segments


def sync_with_database(db_path: Path, full_line: LineString, segments: list[dict]):
    """Tworzy tabelę CircuitTrackSegments i synchronizuje geometrię w LeMans24h.db."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1. Tabela na mikro-odcinki 3D toru
    cur.execute("""
    CREATE TABLE IF NOT EXISTS CircuitTrackSegments (
        SegmentID INTEGER PRIMARY KEY AUTOINCREMENT,
        CircuitID INTEGER,
        SeqID INTEGER,
        EleStart REAL,
        EleEnd REAL,
        EleAvg REAL,
        GeometryWKT TEXT,
        FOREIGN KEY (CircuitID) REFERENCES Circuits(CircuitID)
    );
    """)

    # 2. Czyszczenie starych segmentów i wstawienie nowych
    cur.execute("DELETE FROM CircuitTrackSegments")
    cur.execute("SELECT CircuitID FROM Circuits ORDER BY SinceYear DESC LIMIT 1")
    latest_circuit_row = cur.fetchone()
    circuit_id = latest_circuit_row[0] if latest_circuit_row else 1

    cur.executemany("""
    INSERT INTO CircuitTrackSegments (CircuitID, SeqID, EleStart, EleEnd, EleAvg, GeometryWKT)
    VALUES (?, ?, ?, ?, ?, ?)
    """, [
        (circuit_id, s["seq_id"], s["ele_start"], s["ele_end"], s["ele_avg"], s["geometry"].wkt)
        for s in segments
    ])

    # 3. Aktualizacja pełnej linii WKT toru w tabeli Circuits
    cur.execute(
        "UPDATE Circuits SET GeometryWKT = ? WHERE CircuitID = ?",
        (full_line.wkt, circuit_id)
    )

    conn.commit()
    conn.close()
    print(f"[SQL] Zsynchronizowano bazę {db_path.name}: zapisano {len(segments)} segmentów i geometrię toru.")


def load_segments_from_db(db_path: Path):
    """Pobiera geometrię z bazy danych, jeśli w folderze nie ma pliku GPX."""
    conn = sqlite3.connect(db_path)
    query = "SELECT SeqID AS seq_id, EleStart AS ele_start, EleEnd AS ele_end, EleAvg AS ele_avg, GeometryWKT FROM CircuitTrackSegments ORDER BY SeqID"
    df = pd.read_sql_query(query, conn)
    conn.close()

    df["geometry"] = df["GeometryWKT"].apply(wkt.loads)
    segments = df.drop(columns=["GeometryWKT"]).to_dict("records")
    coords = []
    for s in segments:
        coords.append(s["geometry"].coords[0])
    coords.append(segments[-1]["geometry"].coords[-1])
    return LineString(coords), segments


def export_gpkg(full_line: LineString, segments: list[dict], output_gpkg: Path):
    """Eksportuje wielowarstwowy plik GeoPackage pod wizualizację w QGIS."""
    # 1. Warstwa odcinków pod płynny gradient
    gdf_segments = gpd.GeoDataFrame(segments, crs="EPSG:4326")
    gdf_segments.to_file(output_gpkg, layer="circuit_gradient_track", driver="GPKG")

    # 2. Warstwa pełnej nitki
    gdf_full = gpd.GeoDataFrame([{"Name": "Circuit de la Sarthe", "geometry": full_line}], crs="EPSG:4326")
    gdf_full.to_file(output_gpkg, layer="circuit_track_line", driver="GPKG")

    # 3. Warstwa strefy bezpieczeństwa (bufor 15 m wyznaczony w Lambert-93)
    gdf_metric = gdf_full.to_crs(epsg=2154)
    gdf_buffer = gdf_metric.copy()
    gdf_buffer["geometry"] = gdf_metric.geometry.buffer(15)
    gdf_buffer.to_crs(epsg=4326).to_file(output_gpkg, layer="track_safety_buffer_15m", driver="GPKG")

    print(f"[GPKG] Wygenerowano gotowy plik: {output_gpkg.name}")


def main():
    if GPX_PATH.exists():
        print(f"Wczytywanie z pliku GPX: {GPX_PATH.name}")
        full_line, segments = parse_gpx_to_segments(GPX_PATH)
        if DB_PATH.exists():
            sync_with_database(DB_PATH, full_line, segments)
    elif DB_PATH.exists():
        print(f"Brak pliku GPX. Pobieranie danych przestrzennych bezpośrednio z bazy {DB_PATH.name}...")
        full_line, segments = load_segments_from_db(DB_PATH)
    else:
        raise FileNotFoundError("Nie znaleziono pliku LeMans24hCircuit.gpx ani bazy LeMans24h.db!")

    export_gpkg(full_line, segments, OUTPUT_GPKG)
    print("\nGotowe. Warstwy są gotowe do otwarcia w QGIS.")


if __name__ == "__main__":
    main()