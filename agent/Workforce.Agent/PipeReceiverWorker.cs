using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text.Json;
using Workforce.Agent.Shared;

namespace Workforce.Agent;

public sealed class PipeReceiverWorker : BackgroundService
{
    private readonly ActivityQueue _queue;
    private readonly CurrentActivityState _state;
    private readonly ScreenshotQueue _screenshots;
    private readonly ILogger<PipeReceiverWorker> _logger;
    private readonly DeviceIdentityProvider _identity;
    private readonly ServerClient _server;

    public PipeReceiverWorker(
        ActivityQueue queue,
        CurrentActivityState state,
        ScreenshotQueue screenshots,
        DeviceIdentityProvider identity,
        ServerClient server,
        ILogger<PipeReceiverWorker> logger)
    {
        _queue = queue;
        _state = state;
        _screenshots = screenshots;
        _identity = identity;
        _server = server;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        await _queue.InitializeAsync(stoppingToken);
        await _screenshots.InitializeAsync(stoppingToken);
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var pipeSecurity = new PipeSecurity();
                pipeSecurity.AddAccessRule(new PipeAccessRule(
                    new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null),
                    PipeAccessRights.FullControl,
                    AccessControlType.Allow));
                pipeSecurity.AddAccessRule(new PipeAccessRule(
                    new SecurityIdentifier(WellKnownSidType.AuthenticatedUserSid, null),
                    PipeAccessRights.ReadWrite,
                    AccessControlType.Allow));
                await using var pipe = NamedPipeServerStreamAcl.Create(
                    LocalAgentProtocol.PipeName,
                    PipeDirection.In,
                    NamedPipeServerStream.MaxAllowedServerInstances,
                    PipeTransmissionMode.Byte,
                    PipeOptions.Asynchronous,
                    0,
                    0,
                    pipeSecurity);
                await pipe.WaitForConnectionAsync(stoppingToken);
                using var reader = new StreamReader(pipe);
                var json = await reader.ReadLineAsync(stoppingToken);
                if (string.IsNullOrWhiteSpace(json)) continue;
                var message = JsonSerializer.Deserialize<LocalAgentMessage>(json);
                if (message is null) continue;
                if (!string.IsNullOrWhiteSpace(message.State)) _state.Set(message.State);
                if (message.Kind == LocalMessageKinds.Screenshot && message.Screenshot is not null)
                {
                    await _screenshots.EnqueueAsync(message.Screenshot, stoppingToken);
                    continue;
                }
                if (message.Kind == LocalMessageKinds.SystemEvent && message.SystemEvent is not null)
                {
                    var credentials = await _identity.GetAsync(stoppingToken);
                    await _server.SendSystemEventAsync(
                        credentials, message.SystemEvent.Code, message.SystemEvent.WindowsSessionId,
                        message.SystemEvent.Details, stoppingToken);
                    if (message.SystemEvent.Code == "diagnostic_requested_by_employee")
                        await _server.SendDiagnosticLogsAsync(credentials, "employee_request", stoppingToken);
                    continue;
                }
                if (message.Kind != LocalMessageKinds.ActivityEvent || message.Event is null) continue;
                if (message.Event.EndedAt <= message.Event.StartedAt) continue;
                await _queue.EnqueueAsync(message.Event, stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { }
            catch (Exception exception)
            {
                _logger.LogWarning(exception, "Could not receive activity from session agent");
                await Task.Delay(TimeSpan.FromSeconds(1), stoppingToken);
            }
        }
    }
}
