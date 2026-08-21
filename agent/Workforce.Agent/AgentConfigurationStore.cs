using System.Text.Json;
using Workforce.Agent.Shared;

namespace Workforce.Agent;

public sealed class AgentConfigurationStore
{
    private readonly SemaphoreSlim _gate = new(1, 1);
    private AgentRuntimeConfig _current = AgentRuntimeConfig.LoadFromDisk();

    public AgentRuntimeConfig Current => Volatile.Read(ref _current);
    public string? ETag { get; private set; }

    public async Task SaveAsync(
        AgentRuntimeConfig config,
        string? etag,
        CancellationToken cancellationToken)
    {
        config = config.Validated();
        await _gate.WaitAsync(cancellationToken);
        try
        {
            var path = AgentRuntimeConfig.ConfigPath;
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var temporary = path + ".tmp";
            await File.WriteAllTextAsync(
                temporary,
                JsonSerializer.Serialize(config, new JsonSerializerOptions { WriteIndented = true }),
                cancellationToken);
            File.Move(temporary, path, true);
            Volatile.Write(ref _current, config);
            ETag = etag;
        }
        finally
        {
            _gate.Release();
        }
    }
}
