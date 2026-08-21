using Workforce.SessionAgent;

namespace Workforce.Agent.Shared.Tests;

public sealed class BrowserUrlReaderTests
{
    [Theory]
    [InlineData("https://www.youtube.com/shorts/abc?feature=share", "youtube.com", "/shorts/abc")]
    [InlineData("vk.com/clips/video-1", "vk.com", "/clips/video-1")]
    [InlineData("http://docs.google.com/", "docs.google.com", "/")]
    public void Url_is_reduced_to_domain_and_path(string value, string domain, string path)
    {
        var result = BrowserUrlReader.Normalize(value);

        Assert.NotNull(result);
        Assert.Equal(domain, result.Domain);
        Assert.Equal(path, result.Path);
    }

    [Fact]
    public void Non_http_values_are_rejected()
    {
        Assert.Null(BrowserUrlReader.Normalize("file:///c:/private.txt"));
        Assert.Null(BrowserUrlReader.Normalize("john@example.com"));
    }
}
