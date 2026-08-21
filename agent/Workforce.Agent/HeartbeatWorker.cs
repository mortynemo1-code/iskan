using Microsoft.Extensions.Options;

namespace Workforce.Agent;

public sealed class HeartbeatWorker : BackgroundService
{
    private readonly ServerClient _server;
    private readonly DeviceIdentityProvider _identity;
    private readonly CurrentActivityState _activityState;
    private readonly AgentOptions _options;
    private readonly AgentCommandStore _commands;
    private readonly ILogger<HeartbeatWorker> _logger;
    private readonly ResourceUsageSampler _resources;
    private int _overLimitSamples;

    public HeartbeatWorker(
        ServerClient server,
        DeviceIdentityProvider identity,
        CurrentActivityState activityState,
        AgentCommandStore commands,
        ResourceUsageSampler resources,
        IOptions<AgentOptions> options,
        ILogger<HeartbeatWorker> logger)
    {
        _server = server;
        _identity = identity;
        _activityState = activityState;
        _commands = commands;
        _resources = resources;
        _options = options.Value;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        DeviceCredentials? credentials = null;
        var retrySeconds = 1;
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                credentials ??= await _identity.GetAsync(stoppingToken);
                var usage = _resources.Sample();
                var heartbeat = await _server.SendHeartbeatAsync(credentials, _activityState.Value, usage.CpuPercent, usage.RamMb, stoppingToken);
                await _commands.DispatchAsync(credentials, heartbeat.Commands, _server, stoppingToken);
                var overLimit = usage.Streaming ? usage.CpuPercent > 5 || usage.RamMb > 350 : usage.CpuPercent > 1.5 || usage.RamMb > 150;
                _overLimitSamples = overLimit ? _overLimitSamples + 1 : 0;
                if (_overLimitSamples == 2)
                {
                    _resources.RequestLowProfile();
                    await _server.SendSystemEventAsync(credentials, "resource_limit_warning", null,
                        new Dictionary<string, object?> { ["cpu_percent"] = usage.CpuPercent, ["ram_mb"] = usage.RamMb, ["streaming"] = usage.Streaming }, stoppingToken);
                }
                _logger.LogDebug("Heartbeat sent for {DeviceId}", credentials.DeviceId);
                retrySeconds = 1;
                await Task.Delay(TimeSpan.FromSeconds(_options.HeartbeatIntervalSeconds), stoppingToken);
            }
            catch (Exception exception) when (!stoppingToken.IsCancellationRequested)
            {
                _logger.LogWarning(exception, "Heartbeat failed; retrying in {RetrySeconds}s", retrySeconds);
                await Task.Delay(TimeSpan.FromSeconds(retrySeconds), stoppingToken);
                retrySeconds = Math.Min(retrySeconds * 2, 300);
            }
        }
    }
}
