using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Workforce.Agent;

public sealed class DeviceCredentialsStore
{
    private readonly string _path = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
        "WorkforceMonitoring",
        "device.dat");

    public async Task<DeviceCredentials?> LoadAsync(CancellationToken cancellationToken)
    {
        if (!File.Exists(_path)) return null;
        var encrypted = await File.ReadAllBytesAsync(_path, cancellationToken);
        var plain = ProtectedData.Unprotect(encrypted, null, DataProtectionScope.LocalMachine);
        return JsonSerializer.Deserialize<DeviceCredentials>(plain);
    }

    public async Task SaveAsync(DeviceCredentials credentials, CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(_path)!);
        var plain = JsonSerializer.SerializeToUtf8Bytes(credentials);
        var encrypted = ProtectedData.Protect(plain, null, DataProtectionScope.LocalMachine);
        await File.WriteAllBytesAsync(_path, encrypted, cancellationToken);
    }
}
