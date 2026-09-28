Bieżąca suma zwycięstw marek i ranking historyczny

Oblicza kumulatywną liczbę triumfów dla czołowych producentów rok po roku oraz wyznacza pozycję marki w rankingu wszech czasów w danym punkcie historii.

WITH RaceWinners AS (
    SELECT 
        r.Year,
        c.Make,
        t.TeamName
    FROM Races r
    JOIN RaceEntries re ON r.RaceID = re.RaceID
    JOIN RaceResults rr ON re.EntryID = rr.EntryID
    JOIN Cars c ON re.CarID = c.CarID
    JOIN Teams t ON re.TeamID = t.TeamID
    WHERE rr.FinishingPosition = 1
),
TopMakes AS (
    SELECT Make, COUNT(*) AS TotalWins
    FROM RaceWinners
    GROUP BY Make
    ORDER BY TotalWins DESC
    LIMIT 6
),
CumulativeStats AS (
    SELECT 
        rw.Year,
        rw.Make,
        COUNT(*) OVER (
            PARTITION BY rw.Make 
            ORDER BY rw.Year 
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS CumulativeWins
    FROM RaceWinners rw
    JOIN TopMakes tm ON rw.Make = tm.Make
)
SELECT 
    Year,
    Make,
    CumulativeWins,
    DENSE_RANK() OVER (
        PARTITION BY Year 
        ORDER BY CumulativeWins DESC
    ) AS HistoricalRankAtYear
FROM CumulativeStats
ORDER BY Year ASC, CumulativeWins DESC;