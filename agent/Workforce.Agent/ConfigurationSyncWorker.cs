using Microsoft.Extensions.Options;

namespace Workforce.Agent;

public sealed class ConfigurationSyncWorker : BackgroundService
{
    private readonly DeviceIdentityProvider _identity;
    private readonly ServerClient _server;
    private readonly AgentConfigurationStore _store;
    private readonly AgentOptions _options;
    private readonly ILogger<ConfigurationSyncWorker> _logger;

    public ConfigurationSyncWorker(
        DeviceIdentityProvider identity,
        ServerClient server,
        AgentConfigurationStore store,
        IOptions<AgentOptions> options,
        ILogger<ConfigurationSyncWorker> logger)
    {
        _identity = identity;
        _server = server;
        _store = store;
        _options = options.Value;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var credentials = await _identity.GetAsync(stoppingToken);
                var result = await _server.GetAgentConfigAsync(credentials, _store.ETag, stoppingToken);
                if (result.Config is not null)
                {
                    await _store.SaveAsync(result.Config, result.ETag, stoppingToken);
                    _logger.LogInformation("Agent configuration updated: {ETag}", result.ETag);
                }
            }
            catch (Exception exception) when (!stoppingToken.IsCancellationRequested)
            {
                _logger.LogWarning(exception, "Could not update agent configuration; cached values remain active");
            }
            await Task.Delay(TimeSpan.FromSeconds(_options.ConfigRefreshIntervalSeconds), stoppingToken);
        }
    }
}
