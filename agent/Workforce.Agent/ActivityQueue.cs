using System.Text.Json;
using Microsoft.Data.Sqlite;
using Workforce.Agent.Shared;

namespace Workforce.Agent;

public sealed record QueuedActivityEvent(long Id, LocalActivityEvent Event);

public sealed class ActivityQueue
{
    private const long MaxBytes = 500L * 1024 * 1024;
    private static readonly TimeSpan MaxAge = TimeSpan.FromDays(7);
    private readonly string _databasePath;
    private readonly string _connectionString;
    private readonly SemaphoreSlim _initializationGate = new(1, 1);
    private bool _initialized;

    public ActivityQueue()
    {
        var directory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "WorkforceMonitoring");
        Directory.CreateDirectory(directory);
        _databasePath = Path.Combine(directory, "activity-queue.db");
        _connectionString = new SqliteConnectionStringBuilder
        {
            DataSource = _databasePath,
            Mode = SqliteOpenMode.ReadWriteCreate,
            Cache = SqliteCacheMode.Shared,
        }.ToString();
    }

    public async Task InitializeAsync(CancellationToken cancellationToken)
    {
        if (_initialized) return;
        await _initializationGate.WaitAsync(cancellationToken);
        try
        {
            if (_initialized) return;
            await using var connection = await OpenAsync(cancellationToken);
            var command = connection.CreateCommand();
            command.CommandText = """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS queue_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_uuid TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS queue_events_created_idx ON queue_events(created_at);
                """;
            await command.ExecuteNonQueryAsync(cancellationToken);
            _initialized = true;
        }
        finally
        {
            _initializationGate.Release();
        }
    }

    public async Task EnqueueAsync(LocalActivityEvent item, CancellationToken cancellationToken)
    {
        await using var connection = await OpenAsync(cancellationToken);
        var command = connection.CreateCommand();
        command.CommandText = """
            INSERT OR IGNORE INTO queue_events(event_uuid, payload_json, created_at)
            VALUES($event_uuid, $payload_json, $created_at)
            """;
        command.Parameters.AddWithValue("$event_uuid", item.EventUuid.ToString());
        command.Parameters.AddWithValue("$payload_json", JsonSerializer.Serialize(item));
        command.Parameters.AddWithValue("$created_at", DateTimeOffset.UtcNow.ToString("O"));
        await command.ExecuteNonQueryAsync(cancellationToken);
        await EnforceLimitsAsync(connection, cancellationToken);
    }

    public async Task<IReadOnlyList<QueuedActivityEvent>> TakeAsync(int limit, CancellationToken cancellationToken)
    {
        await using var connection = await OpenAsync(cancellationToken);
        var command = connection.CreateCommand();
        command.CommandText = "SELECT id, payload_json FROM queue_events ORDER BY id LIMIT $limit";
        command.Parameters.AddWithValue("$limit", limit);
        var result = new List<QueuedActivityEvent>(limit);
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        while (await reader.ReadAsync(cancellationToken))
        {
            var item = JsonSerializer.Deserialize<LocalActivityEvent>(reader.GetString(1));
            if (item is not null) result.Add(new QueuedActivityEvent(reader.GetInt64(0), item));
        }
        return result;
    }

    public async Task DeleteAsync(IEnumerable<long> ids, CancellationToken cancellationToken)
    {
        await using var connection = await OpenAsync(cancellationToken);
        await using var transaction = await connection.BeginTransactionAsync(cancellationToken);
        foreach (var id in ids)
        {
            var command = connection.CreateCommand();
            command.Transaction = (SqliteTransaction)transaction;
            command.CommandText = "DELETE FROM queue_events WHERE id=$id";
            command.Parameters.AddWithValue("$id", id);
            await command.ExecuteNonQueryAsync(cancellationToken);
        }
        await transaction.CommitAsync(cancellationToken);
    }

    private async Task<SqliteConnection> OpenAsync(CancellationToken cancellationToken)
    {
        var connection = new SqliteConnection(_connectionString);
        await connection.OpenAsync(cancellationToken);
        return connection;
    }

    private async Task EnforceLimitsAsync(SqliteConnection connection, CancellationToken cancellationToken)
    {
        var removeOld = connection.CreateCommand();
        removeOld.CommandText = "DELETE FROM queue_events WHERE created_at < $cutoff";
        removeOld.Parameters.AddWithValue("$cutoff", DateTimeOffset.UtcNow.Subtract(MaxAge).ToString("O"));
        await removeOld.ExecuteNonQueryAsync(cancellationToken);

        var currentBytes = File.Exists(_databasePath) ? new FileInfo(_databasePath).Length : 0;
        var walPath = _databasePath + "-wal";
        if (File.Exists(walPath)) currentBytes += new FileInfo(walPath).Length;
        if (currentBytes <= MaxBytes) return;
        var trim = connection.CreateCommand();
        trim.CommandText = """
            DELETE FROM queue_events WHERE id IN (
                SELECT id FROM queue_events ORDER BY id LIMIT 5000
            )
            """;
        await trim.ExecuteNonQueryAsync(cancellationToken);
        var checkpoint = connection.CreateCommand();
        checkpoint.CommandText = "PRAGMA wal_checkpoint(TRUNCATE)";
        await checkpoint.ExecuteNonQueryAsync(cancellationToken);
    }
}
