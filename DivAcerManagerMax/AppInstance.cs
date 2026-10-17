// SPDX-License-Identifier: GPL-3.0-only
// Native PH16-72 edition; modified October 2026. See NOTICE.md.
using System;
using System.IO;
using System.IO.Pipes;
using System.Threading;
using System.Threading.Tasks;

namespace DivAcerManagerMax;

internal sealed class AppInstance : IDisposable
{
    private readonly string _name;
    private readonly FileStream _lock;
    private readonly CancellationTokenSource _stop = new();
    public bool IsPrimary { get; }

    public AppInstance(string? name = null)
    {
        _name = name ?? "damx-" + Environment.UserName;
        var runtime = Environment.GetEnvironmentVariable("XDG_RUNTIME_DIR") ?? Path.GetTempPath();
        _lock = new FileStream(Path.Combine(runtime, _name + ".lock"), new FileStreamOptions
        {
            Mode = FileMode.OpenOrCreate, Access = FileAccess.ReadWrite, Share = FileShare.ReadWrite,
            UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite
        });
        // User-manager launches have separate sessions; their default named
        // mutexes do not coordinate. A runtime-directory lock crosses sessions.
        try { _lock.Lock(0, 1); IsPrimary = true; }
        catch (IOException) { IsPrimary = false; }
    }

    public void Listen(Action activate) => Task.Run(async () =>
    {
        while (!_stop.IsCancellationRequested)
        {
            using var pipe = new NamedPipeServerStream(_name, PipeDirection.In, 1,
                PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
            try
            {
                await pipe.WaitForConnectionAsync(_stop.Token);
                var data = new byte[1];
                using var timeout = CancellationTokenSource.CreateLinkedTokenSource(_stop.Token);
                timeout.CancelAfter(2000);
                if (await pipe.ReadAsync(data, timeout.Token) == 1 && data[0] == 1) activate();
            }
            catch (OperationCanceledException) { }
            catch (System.IO.IOException) { }
        }
    });

    public void Activate()
    {
        using var pipe = new NamedPipeClientStream(".", _name, PipeDirection.Out, PipeOptions.CurrentUserOnly);
        pipe.Connect(3000);
        pipe.WriteByte(1);
    }

    public void Dispose()
    {
        _stop.Cancel();
        _lock.Dispose();
    }
}
