using NAudio.CoreAudioApi;

namespace Workforce.SessionAgent;

public sealed class MediaPlaybackDetector
{
    public bool IsProcessRenderingAudio(uint processId)
    {
        if (processId == 0) return false;
        try
        {
            using var devices = new MMDeviceEnumerator();
            using var endpoint = devices.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);
            var sessions = endpoint.AudioSessionManager.Sessions;
            for (var index = 0; index < sessions.Count; index++)
            {
                using var session = sessions[index];
                if (session.State == AudioSessionState.AudioSessionStateActive && session.GetProcessID == processId)
                    return true;
            }
        }
        catch
        {
            // Audio service/device changes are expected; activity collection continues normally.
        }
        return false;
    }
}
