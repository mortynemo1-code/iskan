using System.Drawing.Imaging;
using Workforce.Agent.Shared;

namespace Workforce.SessionAgent;

public sealed class ScreenshotCapturer
{
    public IReadOnlyList<LocalScreenshot> Capture(ActivitySample sample, AgentRuntimeConfig config)
    {
        if (config.ScreenshotAllMonitors && config.ScreenshotMultiMonitorMode == "separate")
            return Screen.AllScreens.Select((screen, index) => CaptureBounds(sample, config, screen.Bounds, index)).ToArray();
        var active = Screen.FromPoint(Cursor.Position);
        var bounds = config.ScreenshotAllMonitors ? SystemInformation.VirtualScreen : active.Bounds;
        var monitorIndex = config.ScreenshotAllMonitors ? 0 : Math.Max(0, Array.IndexOf(Screen.AllScreens, active));
        return [CaptureBounds(sample, config, bounds, monitorIndex)];
    }

    private static LocalScreenshot CaptureBounds(ActivitySample sample, AgentRuntimeConfig config, Rectangle bounds, int monitorIndex)
    {
        using var source = new Bitmap(bounds.Width, bounds.Height, PixelFormat.Format24bppRgb);
        using (var graphics = Graphics.FromImage(source))
            graphics.CopyFromScreen(bounds.Left, bounds.Top, 0, 0, bounds.Size, CopyPixelOperation.SourceCopy);
        var isBlurred = ShouldBlur(sample, config);
        using var protectedImage = isBlurred ? Pixelate(source) : new Bitmap(source);
        using var scaled = Scale(protectedImage, config.ScreenshotMaxLongSide);
        using var thumbnail = Scale(scaled, 320);
        var imageBytes = EncodeJpeg(scaled, config.ScreenshotQuality);
        var thumbBytes = EncodeJpeg(thumbnail, Math.Min(config.ScreenshotQuality, 75));
        return new LocalScreenshot(
            sample.CapturedAt,
            scaled.Width,
            scaled.Height,
            monitorIndex,
            AverageHash(scaled),
            sample.State,
            sample.AppName ?? sample.ProcessName,
            sample.UrlDomain,
            Convert.ToBase64String(imageBytes),
            Convert.ToBase64String(thumbBytes),
            isBlurred);
    }

    private static bool ShouldBlur(ActivitySample sample, AgentRuntimeConfig config)
    {
        if (config.ScreenshotBlurMode.Equals("full", StringComparison.OrdinalIgnoreCase)) return true;
        if (!config.ScreenshotBlurMode.Equals("private_apps", StringComparison.OrdinalIgnoreCase)) return false;
        var value = $"{sample.ProcessName} {sample.AppName} {sample.WindowTitle} {sample.UrlDomain}";
        return (config.PrivateAppPatterns ?? []).Any(pattern =>
            !string.IsNullOrWhiteSpace(pattern) && value.Contains(pattern, StringComparison.OrdinalIgnoreCase));
    }

    private static Bitmap Pixelate(Image source)
    {
        var tinyWidth = Math.Clamp(source.Width / 32, 16, 64);
        var tinyHeight = Math.Clamp(source.Height / 32, 12, 64);
        using var tiny = new Bitmap(tinyWidth, tinyHeight, PixelFormat.Format24bppRgb);
        using (var graphics = Graphics.FromImage(tiny))
        {
            graphics.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.Bilinear;
            graphics.DrawImage(source, 0, 0, tiny.Width, tiny.Height);
        }
        var result = new Bitmap(source.Width, source.Height, PixelFormat.Format24bppRgb);
        using (var graphics = Graphics.FromImage(result))
        {
            graphics.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.NearestNeighbor;
            graphics.PixelOffsetMode = System.Drawing.Drawing2D.PixelOffsetMode.Half;
            graphics.DrawImage(tiny, 0, 0, result.Width, result.Height);
        }
        return result;
    }

    private static Bitmap Scale(Image source, int maxLongSide)
    {
        var scale = Math.Min(1d, maxLongSide / (double)Math.Max(source.Width, source.Height));
        var width = Math.Max(1, (int)Math.Round(source.Width * scale));
        var height = Math.Max(1, (int)Math.Round(source.Height * scale));
        var result = new Bitmap(width, height, PixelFormat.Format24bppRgb);
        using var graphics = Graphics.FromImage(result);
        graphics.CompositingQuality = System.Drawing.Drawing2D.CompositingQuality.HighQuality;
        graphics.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;
        graphics.DrawImage(source, 0, 0, width, height);
        return result;
    }

    private static byte[] EncodeJpeg(Image image, int quality)
    {
        using var output = new MemoryStream();
        var codec = ImageCodecInfo.GetImageEncoders().First(item => item.FormatID == ImageFormat.Jpeg.Guid);
        using var parameters = new EncoderParameters(1);
        parameters.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, quality);
        image.Save(output, codec, parameters);
        return output.ToArray();
    }

    internal static string AverageHash(Image image)
    {
        using var tiny = new Bitmap(image, new Size(8, 8));
        var values = new byte[64];
        var sum = 0;
        for (var y = 0; y < 8; y++)
        for (var x = 0; x < 8; x++)
        {
            var color = tiny.GetPixel(x, y);
            var gray = (byte)((color.R * 299 + color.G * 587 + color.B * 114) / 1000);
            values[y * 8 + x] = gray;
            sum += gray;
        }
        var average = sum / 64;
        ulong hash = 0;
        for (var index = 0; index < values.Length; index++)
            if (values[index] >= average) hash |= 1UL << index;
        return hash.ToString("x16");
    }
}
