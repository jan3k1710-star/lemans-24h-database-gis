WITH WinnersHistory AS (
    SELECT 
        r.Year,
        c.Make,
        LAG(c.Make) OVER (ORDER BY r.Year) AS PrevMake,
        LAG(r.Year) OVER (ORDER BY r.Year) AS PrevYear
    FROM Races r
    JOIN RaceEntries re ON r.RaceID = re.RaceID
    JOIN RaceResults rr ON re.EntryID = rr.EntryID
    JOIN Cars c ON re.CarID = c.CarID
    WHERE rr.FinishingPosition = 1
),
StreakGroups AS (
    SELECT 
        Year,
        Make,
        SUM(CASE 
            WHEN PrevMake = Make AND Year = PrevYear + 1 THEN 0 
            ELSE 1 
        END) OVER (ORDER BY Year) AS IslandGroupID
    FROM WinnersHistory
),
StreakCalculations AS (
    SELECT 
        Make,
        MIN(Year) AS StreakStart,
        MAX(Year) AS StreakEnd,
        COUNT(*) AS ConsecutiveWins
    FROM StreakGroups
    GROUP BY Make, IslandGroupID
)
SELECT 
    Make,
    StreakStart,
    StreakEnd,
    ConsecutiveWins,
    DENSE_RANK() OVER (ORDER BY ConsecutiveWins DESC) AS AllTimeStreakRank
FROM StreakCalculations
WHERE ConsecutiveWins >= 2
ORDER BY ConsecutiveWins DESC, StreakStart ASC;