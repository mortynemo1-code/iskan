using System.Windows.Automation;
using System.Runtime.InteropServices;

namespace Workforce.SessionAgent;

public sealed record BrowserLocation(string Domain, string Path);

public sealed class BrowserUrlReader
{
    private static readonly HashSet<string> BrowserProcesses = new(StringComparer.OrdinalIgnoreCase)
    {
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "browser.exe",
        "vivaldi.exe",
        "opera.exe",
    };

    public BrowserLocation? Read(nint window, string? processName)
    {
        if (window == 0 || processName is null || !BrowserProcesses.Contains(processName)) return null;
        try
        {
            var root = AutomationElement.FromHandle(window);
            var edits = root.FindAll(
                TreeScope.Descendants,
                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Edit));
            foreach (AutomationElement edit in edits)
            {
                if (!IsAddressBar(edit)) continue;
                if (!edit.TryGetCurrentPattern(ValuePattern.Pattern, out var pattern)) continue;
                var value = ((ValuePattern)pattern).Current.Value;
                var normalized = Normalize(value);
                if (normalized is not null) return normalized;
            }
        }
        catch (ElementNotAvailableException) { }
        catch (UnauthorizedAccessException) { }
        catch (COMException) { }
        return null;
    }

    private static bool IsAddressBar(AutomationElement element)
    {
        var identity = $"{element.Current.Name} {element.Current.AutomationId}".ToLowerInvariant();
        return identity.Contains("address") ||
               identity.Contains("urlbar") ||
               identity.Contains("omnibox") ||
               identity.Contains("адрес") ||
               identity.Contains("умная строка");
    }

    public static BrowserLocation? Normalize(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return null;
        value = value.Trim();
        if (value.StartsWith("view-source:", StringComparison.OrdinalIgnoreCase))
            value = value[12..];
        if (!value.Contains("://", StringComparison.Ordinal))
            value = "https://" + value;
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri)) return null;
        if (uri.Scheme is not ("http" or "https") || string.IsNullOrWhiteSpace(uri.Host)) return null;
        if (!string.IsNullOrEmpty(uri.UserInfo)) return null;
        var domain = uri.IdnHost.ToLowerInvariant();
        if (domain.StartsWith("www.", StringComparison.Ordinal)) domain = domain[4..];
        var path = string.IsNullOrEmpty(uri.AbsolutePath) ? "/" : uri.AbsolutePath;
        return new BrowserLocation(domain[..Math.Min(domain.Length, 255)], path[..Math.Min(path.Length, 2048)]);
    }
}
