namespace Workforce.Agent;

public sealed class CommandPollingWorker : BackgroundService
{
    private readonly DeviceIdentityProvider _identity;
    private readonly ServerClient _server;
    private readonly AgentCommandStore _store;
    private readonly ILogger<CommandPollingWorker> _logger;

    public CommandPollingWorker(
        DeviceIdentityProvider identity,
        ServerClient server,
        AgentCommandStore store,
        ILogger<CommandPollingWorker> logger)
    {
        _identity = identity;
        _server = server;
        _store = store;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var retrySeconds = 1;
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var credentials = await _identity.GetAsync(stoppingToken);
                var commands = await _server.GetCommandsAsync(credentials, stoppingToken);
                await _store.DispatchAsync(credentials, commands, _server, stoppingToken);
                retrySeconds = 1;
                await Task.Delay(TimeSpan.FromSeconds(2), stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { }
            catch (Exception exception)
            {
                _logger.LogWarning(exception, "Command polling failed");
                await Task.Delay(TimeSpan.FromSeconds(retrySeconds), stoppingToken);
                retrySeconds = Math.Min(retrySeconds * 2, 60);
            }
        }
    }
}
