namespace Workforce.Agent;

public sealed class UpdateSignal
{
    private readonly SemaphoreSlim _signal = new(0, 1);
    public void Trigger() { if (_signal.CurrentCount == 0) _signal.Release(); }
    public Task<bool> WaitAsync(TimeSpan timeout, CancellationToken cancellationToken) => _signal.WaitAsync(timeout, cancellationToken);
}
