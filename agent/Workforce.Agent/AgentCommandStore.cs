using System.Text.Json;
using Workforce.Agent.Shared;

namespace Workforce.Agent;

public sealed class AgentCommandStore
{
    private readonly SemaphoreSlim _gate = new(1, 1);
    private readonly UpdateSignal _updates;

    public AgentCommandStore(UpdateSignal updates) => _updates = updates;

    public async Task DispatchAsync(
        DeviceCredentials credentials,
        IEnumerable<AgentCommand> commands,
        ServerClient server,
        CancellationToken cancellationToken)
    {
        await _gate.WaitAsync(cancellationToken);
        try
        {
            Directory.CreateDirectory(LocalAgentProtocol.CommandDirectory);
            foreach (var command in commands)
            {
                try
                {
                    if (command.Command == "send_logs")
                    {
                        await server.SendDiagnosticLogsAsync(credentials, "admin_command", cancellationToken);
                        await server.AcknowledgeCommandAsync(credentials, command.Id, true, "Диагностика отправлена", cancellationToken);
                        continue;
                    }
                    if (command.Command == "update_agent")
                    {
                        _updates.Trigger();
                        await server.AcknowledgeCommandAsync(credentials, command.Id, true, "Проверка обновлений запущена", cancellationToken);
                        continue;
                    }
                    if (command.Command == "restart_agent")
                    {
                        await server.AcknowledgeCommandAsync(credentials, command.Id, true, "Служба перезапускается", cancellationToken);
                        _ = Task.Run(async () => { await Task.Delay(1000); Environment.Exit(0); });
                        continue;
                    }
                    var destination = Path.Combine(LocalAgentProtocol.CommandDirectory, $"{command.Id:N}.json");
                    var temporary = destination + ".tmp";
                    await File.WriteAllTextAsync(temporary, JsonSerializer.Serialize(command), cancellationToken);
                    File.Move(temporary, destination, true);
                    await server.AcknowledgeCommandAsync(credentials, command.Id, true, "Передано в интерактивную сессию", cancellationToken);
                }
                catch (Exception exception)
                {
                    await server.AcknowledgeCommandAsync(credentials, command.Id, false, exception.Message, cancellationToken);
                }
            }
        }
        finally
        {
            _gate.Release();
        }
    }
}
