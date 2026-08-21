namespace Workforce.Agent;

public sealed class ActivityUploadWorker : BackgroundService
{
    private readonly ActivityQueue _queue;
    private readonly DeviceIdentityProvider _identity;
    private readonly ServerClient _server;
    private readonly AgentConfigurationStore _configuration;
    private readonly ILogger<ActivityUploadWorker> _logger;

    public ActivityUploadWorker(
        ActivityQueue queue,
        DeviceIdentityProvider identity,
        ServerClient server,
        AgentConfigurationStore configuration,
        ILogger<ActivityUploadWorker> logger)
    {
        _queue = queue;
        _identity = identity;
        _server = server;
        _configuration = configuration;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        await _queue.InitializeAsync(stoppingToken);
        var retrySeconds = 1;
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var runtimeConfig = _configuration.Current;
                var batch = await _queue.TakeAsync(runtimeConfig.BatchSize, stoppingToken);
                if (batch.Count > 0)
                {
                    var credentials = await _identity.GetAsync(stoppingToken);
                    var result = await _server.SendActivityBatchAsync(
                        credentials,
                        batch.Select(item => item.Event).ToArray(),
                        stoppingToken);
                    await _queue.DeleteAsync(batch.Select(item => item.Id), stoppingToken);
                    _logger.LogInformation(
                        "Activity batch uploaded: accepted={Accepted}, duplicates={Duplicates}",
                        result.Accepted,
                        result.Duplicates);
                }
                retrySeconds = 1;
                await Task.Delay(TimeSpan.FromSeconds(runtimeConfig.BatchIntervalSeconds), stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { }
            catch (Exception exception)
            {
                _logger.LogWarning(exception, "Activity upload failed; retrying in {RetrySeconds}s", retrySeconds);
                var jitter = Random.Shared.NextDouble() * Math.Min(10, retrySeconds);
                await Task.Delay(TimeSpan.FromSeconds(retrySeconds + jitter), stoppingToken);
                retrySeconds = Math.Min(retrySeconds * 2, 300);
            }
        }
    }
}
