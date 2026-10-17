using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using DivAcerManagerMax;

static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }
if (args.Length == 2 && args[0] == "--instance-child")
{
    using var child = new AppInstance(args[1]);
    Check(!child.IsPrimary, "Second process must reuse the primary instance");
    child.Activate();
    return;
}
var instanceName = "damx-test-" + Guid.NewGuid().ToString("N");
using (var instance = new AppInstance(instanceName))
using (var activated = new ManualResetEventSlim())
{
    Check(instance.IsPrimary, "First instance must own the runtime lock");
    instance.Listen(activated.Set);
    var start = new System.Diagnostics.ProcessStartInfo(Environment.ProcessPath!) { UseShellExecute = false };
    if (Path.GetFileNameWithoutExtension(Environment.ProcessPath) == "dotnet")
        start.ArgumentList.Add(System.Reflection.Assembly.GetExecutingAssembly().Location);
    start.ArgumentList.Add("--instance-child");
    start.ArgumentList.Add(instanceName);
    using var process = System.Diagnostics.Process.Start(start)!;
    await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(10));
    Check(process.ExitCode == 0 && activated.Wait(3000), "Second launch must activate primary over a user-only pipe");
}
using (var reopened = new AppInstance(instanceName))
    Check(reopened.IsPrimary, "Primary exit must release the lock for the next launch");
File.Delete(Path.Combine(Environment.GetEnvironmentVariable("XDG_RUNTIME_DIR") ?? Path.GetTempPath(), instanceName + ".lock"));
Check(NvidiaTelemetry.Parse("40, 0, 200, 12282, 1.57, 588.21, 175").Watts == 1.57, "Prefer one-second average over bogus wake reading");
Check(NvidiaTelemetry.Parse("40, 0, 200, 12282, N/A, 588.21, 175").Watts is null, "Impossible power must be unavailable");
Check(NvidiaTelemetry.Parse("40, 80, 9000, 12282, N/A, 140.5, 175").Watts == 140.5, "Older drivers may supply only current draw");
Check(NvidiaTelemetry.Parse("40, 0, N/A, N/A, 0, N/A, N/A").Watts == 0, "Zero watts is valid even when VRAM is unavailable");
Check(NvidiaTelemetry.Parse("40, 0, 200, 12282, NaN, Infinity, 175").Watts is null, "Reject nonfinite samples");
Check(NvidiaTelemetry.Parse("failed").Watts is null, "Missing telemetry must not become zero watts");
using (var malformed = JsonDocument.Parse("""{"mode":"broken","brightness":999,"color":null} """))
    Check(LightingDraft.FromState(malformed.RootElement) == new LightingDraft(), "Malformed saved state must use defaults");
using (var state = JsonDocument.Parse("""{"mode":9,"color":"ff2300","link_wasd":false,"speed":7} """))
    Check(LightingDraft.FromState(state.RootElement) == new LightingDraft(9, "#ff2300", 100, 7, 1, false), "Device settings and link choice must survive reload");

var path = Path.Combine(Path.GetTempPath(), "damx-client-" + Guid.NewGuid().ToString("N") + ".sock");
Environment.SetEnvironmentVariable("DAMX_SOCKET_PATH", path);
using var stop = new CancellationTokenSource();
using var listener = new Socket(AddressFamily.Unix, SocketType.Stream, ProtocolType.Unspecified);
listener.Bind(new UnixDomainSocketEndPoint(path));
listener.Listen(5);
var handlers = new List<Task>();
async Task Handle(Socket peer)
{
    using (peer)
    using (var stream = new NetworkStream(peer))
    using (var reader = new StreamReader(stream))
    {
        try
        {
            while (await reader.ReadLineAsync(stop.Token) is { } line)
            {
                using var request = JsonDocument.Parse(line);
                var command = request.RootElement.GetProperty("command").GetString();
                var json = command == "reject" ? "{\"success\":false,\"error\":\"Firmware rejected\"}" :
                    JsonSerializer.Serialize(new { success = true, data = new { thermal_profile = new { current = "balanced", available = new[] { "balanced" } }, padding = new string('x', 12000) } });
                var bytes = Encoding.UTF8.GetBytes(json + "\n");
                // Deliberately fragment a response larger than the receive buffer.
                for (var offset = 0; offset < bytes.Length; offset += 127)
                    await stream.WriteAsync(bytes.AsMemory(offset, Math.Min(127, bytes.Length - offset)), stop.Token);
            }
        }
        catch (Exception e) when (e is OperationCanceledException or IOException or SocketException) { }
    }
}
var accepting = Task.Run(async () => {
    try { while (!stop.IsCancellationRequested) handlers.Add(Handle(await listener.AcceptAsync(stop.Token))); }
    catch (OperationCanceledException) { }
});
try
{
    using var client = new DAMXClient();
    var reads = await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => client.GetAllSettingsAsync()));
    Check(reads.All(r => r.ThermalProfile.Current == "balanced"), "Concurrent responses must not mix");
    try { using var response = await client.SendCommandAsync("reject"); throw new Exception("Daemon error was ignored"); }
    catch (InvalidOperationException e) { Check(e.Message == "Firmware rejected", "Daemon error must reach caller"); }
    Check((await client.GetAllSettingsAsync()).ThermalProfile.Current == "balanced", "Client must reconnect after error");
    client.Dispose();
    try { await client.GetAllSettingsAsync(); throw new Exception("Disposed client reconnected"); }
    catch (ObjectDisposedException) { }
    Console.WriteLine("PASS: fragmented large responses, concurrent reads, error propagation, reconnect, disposal, and lighting state parsing");
}
finally
{
    stop.Cancel();
    await accepting;
    await Task.WhenAll(handlers);
    File.Delete(path);
}
