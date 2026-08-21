namespace Workforce.Agent;

public sealed class ScreenshotUploadWorker : BackgroundService
{
    private readonly ScreenshotQueue _queue;
    private readonly DeviceIdentityProvider _identity;
    private readonly ServerClient _server;
    private readonly ILogger<ScreenshotUploadWorker> _logger;

    public ScreenshotUploadWorker(
        ScreenshotQueue queue,
        DeviceIdentityProvider identity,
        ServerClient server,
        ILogger<ScreenshotUploadWorker> logger)
    {
        _queue = queue;
        _identity = identity;
        _server = server;
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
                var screenshot = await _queue.TakeAsync(stoppingToken);
                if (screenshot is null)
                {
                    await Task.Delay(TimeSpan.FromSeconds(5), stoppingToken);
                    continue;
                }
                var credentials = await _identity.GetAsync(stoppingToken);
                await _server.SendScreenshotAsync(credentials, screenshot, stoppingToken);
                await _queue.DeleteAsync(screenshot, stoppingToken);
                retrySeconds = 1;
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { }
            catch (Exception exception)
            {
                _logger.LogWarning(exception, "Screenshot upload failed; retrying in {RetrySeconds}s", retrySeconds);
                var jitter = Random.Shared.NextDouble() * Math.Min(10, retrySeconds);
                await Task.Delay(TimeSpan.FromSeconds(retrySeconds + jitter), stoppingToken);
                retrySeconds = Math.Min(retrySeconds * 2, 300);
            }
        }
    }
}
