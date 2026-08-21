using System.Diagnostics;
using System.Text.Json;

namespace Workforce.Agent;

public sealed record AgentResourceUsage(double CpuPercent, long RamMb, bool Streaming);

public sealed class ResourceUsageSampler
{
    private DateTimeOffset _lastAt = DateTimeOffset.UtcNow;
    private TimeSpan _lastCpu = TimeSpan.Zero;

    public AgentResourceUsage Sample()
    {
        var processes = RelevantProcesses();
        try
        {
            var now = DateTimeOffset.UtcNow;
            var cpu = processes.Aggregate(TimeSpan.Zero, (total, process) => total + SafeCpu(process));
            var ram = processes.Sum(SafeMemory) / 1024 / 1024;
            var elapsed = now - _lastAt;
            var percent = elapsed.TotalMilliseconds <= 0 ? 0 : Math.Max(0,
                (cpu - _lastCpu).TotalMilliseconds / elapsed.TotalMilliseconds / Environment.ProcessorCount * 100);
            _lastCpu = cpu;
            _lastAt = now;
            return new AgentResourceUsage(Math.Round(percent, 2), ram, processes.Any(p => SafeName(p).Equals("ffmpeg", StringComparison.OrdinalIgnoreCase)));
        }
        finally { foreach (var process in processes) process.Dispose(); }
    }

    public void RequestLowProfile()
    {
        Directory.CreateDirectory(Workforce.Agent.Shared.LocalAgentProtocol.CommandDirectory);
        var id = Guid.NewGuid();
        var command = new AgentCommand(id, "resource_throttle", JsonSerializer.SerializeToElement(new { reason = "resource_limit" }));
        var path = Path.Combine(Workforce.Agent.Shared.LocalAgentProtocol.CommandDirectory, $"{id:N}.json");
        File.WriteAllText(path, JsonSerializer.Serialize(command));
    }

    private static List<Process> RelevantProcesses()
    {
        var result = new Dictionary<int, Process>();
        foreach (var process in new[] { Process.GetCurrentProcess() }
            .Concat(Process.GetProcessesByName("Workforce.SessionAgent"))
            .Concat(Process.GetProcessesByName("ffmpeg")))
        {
            try
            {
                if (!result.TryAdd(process.Id, process)) process.Dispose();
            }
            catch { process.Dispose(); }
        }
        return result.Values.ToList();
    }

    private static TimeSpan SafeCpu(Process process) { try { return process.TotalProcessorTime; } catch { return TimeSpan.Zero; } }
    private static long SafeMemory(Process process) { try { return process.WorkingSet64; } catch { return 0; } }
    private static string SafeName(Process process) { try { return process.ProcessName; } catch { return ""; } }
}
