using System.IO.Pipes;
using System.Text.Json;
using System.Threading.Channels;
using Workforce.Agent.Shared;

namespace Workforce.SessionAgent;

public sealed class PipeEventSink : IAsyncDisposable
{
    private readonly Channel<LocalAgentMessage> _events = Channel.CreateBounded<LocalAgentMessage>(
        new BoundedChannelOptions(2000) { FullMode = BoundedChannelFullMode.Wait, SingleReader = true });
    private readonly CancellationTokenSource _stopping = new();
    private readonly Task _sender;
    public DateTimeOffset? LastDeliveryAt { get; private set; }

    public PipeEventSink() => _sender = Task.Run(SendLoopAsync);

    public ValueTask EnqueueEventAsync(LocalActivityEvent activityEvent, CancellationToken cancellationToken = default) =>
        _events.Writer.WriteAsync(LocalAgentMessage.ForEvent(activityEvent), cancellationToken);

    public ValueTask EnqueueStatusAsync(string state, CancellationToken cancellationToken = default) =>
        _events.Writer.WriteAsync(LocalAgentMessage.ForStatus(state), cancellationToken);

    public ValueTask EnqueueScreenshotAsync(LocalScreenshot screenshot, CancellationToken cancellationToken = default) =>
        _events.Writer.WriteAsync(LocalAgentMessage.ForScreenshot(screenshot), cancellationToken);

    public ValueTask EnqueueSystemEventAsync(LocalSystemEvent systemEvent, CancellationToken cancellationToken = default) =>
        _events.Writer.WriteAsync(LocalAgentMessage.ForSystemEvent(systemEvent), cancellationToken);

    private async Task SendLoopAsync()
    {
        await foreach (var item in _events.Reader.ReadAllAsync(_stopping.Token))
        {
            var delivered = false;
            while (!delivered && !_stopping.IsCancellationRequested)
            {
                try
                {
                    await using var pipe = new NamedPipeClientStream(
                        ".", LocalAgentProtocol.PipeName, PipeDirection.Out, PipeOptions.Asynchronous);
                    await pipe.ConnectAsync(2000, _stopping.Token);
                    await using var writer = new StreamWriter(pipe) { AutoFlush = true };
                    await writer.WriteLineAsync(JsonSerializer.Serialize(item));
                    LastDeliveryAt = DateTimeOffset.UtcNow;
                    delivered = true;
                }
                catch (Exception) when (!_stopping.IsCancellationRequested)
                {
                    await Task.Delay(TimeSpan.FromSeconds(2), _stopping.Token);
                }
            }
        }
    }

    public async ValueTask DisposeAsync()
    {
        _events.Writer.TryComplete();
        try
        {
            await _sender.WaitAsync(TimeSpan.FromSeconds(3));
        }
        catch (TimeoutException)
        {
            await _stopping.CancelAsync();
            try { await _sender; } catch (OperationCanceledException) { }
        }
        _stopping.Dispose();
    }
}
