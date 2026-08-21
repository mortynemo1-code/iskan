namespace Workforce.Agent;

public sealed class DeviceIdentityProvider
{
    private readonly DeviceCredentialsStore _store;
    private readonly ServerClient _server;
    private readonly ILogger<DeviceIdentityProvider> _logger;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private DeviceCredentials? _cached;

    public DeviceIdentityProvider(
        DeviceCredentialsStore store,
        ServerClient server,
        ILogger<DeviceIdentityProvider> logger)
    {
        _store = store;
        _server = server;
        _logger = logger;
    }

    public async Task<DeviceCredentials> GetAsync(CancellationToken cancellationToken)
    {
        if (_cached is not null) return _cached;
        await _gate.WaitAsync(cancellationToken);
        try
        {
            if (_cached is not null) return _cached;
            _cached = await _store.LoadAsync(cancellationToken);
            if (_cached is not null) return _cached;

            var registered = await _server.RegisterAsync(cancellationToken);
            _cached = new DeviceCredentials(registered.DeviceId, registered.DeviceToken);
            await _store.SaveAsync(_cached, cancellationToken);
            _logger.LogInformation(
                "Device {DeviceId} registered; approval required: {ApprovalRequired}",
                registered.DeviceId,
                registered.ApprovalRequired);
            return _cached;
        }
        finally
        {
            _gate.Release();
        }
    }
}
