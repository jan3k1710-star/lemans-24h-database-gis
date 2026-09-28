WITH DecadeParticipation AS (
    SELECT 
        (r.Year / 10) * 10 AS Decade,
        c.Make,
        COUNT(*) AS TotalEntries,
        SUM(CASE WHEN rr.Status = 'Finished' THEN 1 ELSE 0 END) AS TotalFinished,
        SUM(CASE WHEN rr.Status = 'DNF' THEN 1 ELSE 0 END) AS TotalDNF,
        SUM(CASE WHEN rr.FinishingPosition = 1 THEN 1 ELSE 0 END) AS TotalWins
    FROM RaceEntries re
    JOIN Races r ON re.RaceID = r.RaceID
    JOIN Cars c ON re.CarID = c.CarID
    JOIN RaceResults rr ON re.EntryID = rr.EntryID
    GROUP BY Decade, c.Make
    HAVING TotalEntries >= 20
),
ReliabilityCalculation AS (
    SELECT 
        Decade,
        Make,
        TotalEntries,
        TotalFinished,
        TotalDNF,
        TotalWins,
        ROUND(CAST(TotalFinished AS REAL) / TotalEntries * 100, 2) AS ReliabilityPct
    FROM DecadeParticipation
)
SELECT 
    Decade || 's' AS Era,
    Make,
    TotalEntries,
    TotalFinished,
    TotalDNF,
    ReliabilityPct,
    TotalWins,
    DENSE_RANK() OVER (
        PARTITION BY Decade 
        ORDER BY TotalWins DESC, ReliabilityPct DESC
    ) AS EraRank
FROM ReliabilityCalculation
ORDER BY Decade DESC, TotalWins DESC, ReliabilityPct DESC;