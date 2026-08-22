// Phase 1: the Tauri shell does nothing beyond hosting the web UI window.
// It intentionally exposes zero `invoke`-able commands yet -- PC control,
// Android control, and voice capture will each be added as their own
// phase, behind the Tool Registry and Permission Manager, not bolted on
// here ad hoc.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    ultron_desktop_lib::run();
}
