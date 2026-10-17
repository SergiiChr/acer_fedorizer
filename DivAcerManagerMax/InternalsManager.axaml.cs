// SPDX-License-Identifier: GPL-3.0-only
// Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
using System;
using System.Text.Json;
using Avalonia.Controls;
using Avalonia.Interactivity;
namespace DivAcerManagerMax;
public partial class InternalsManager : Window
{
    private readonly MainWindow _main;
    public InternalsManager(MainWindow main)
    {
        InitializeComponent();
        _main = main;
        Loaded += Refresh_Click;
    }
    private async void Refresh_Click(object? sender, RoutedEventArgs e)
    {
        try
        {
            using var response = await _main._client.SendCommandAsync("get_all_settings");
            Diagnostics.Text = JsonSerializer.Serialize(response.RootElement, new JsonSerializerOptions { WriteIndented = true });
        }
        catch (Exception ex) { Diagnostics.Text = ex.Message; }
    }
}
