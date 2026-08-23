#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            use tauri::Manager;
            use tauri_plugin_shell::{ShellExt, process::CommandEvent};
            use std::time::Duration;
            
            let app_handle = app.handle().clone();
            
            tauri::async_runtime::spawn(async move {
                let mut attempt = 0;
                let max_attempts = 3;
                
                while attempt < max_attempts {
                    attempt += 1;
                    println!("Spawning ultron-backend sidecar (Attempt {}/{})", attempt, max_attempts);
                    
                    let shell = app_handle.shell();
                    let (mut rx, mut child) = match shell.sidecar("ultron-backend") {
                        Ok(command) => match command.spawn() {
                            Ok(res) => res,
                            Err(e) => {
                                eprintln!("Failed to spawn sidecar: {}", e);
                                tokio::time::sleep(Duration::from_secs(2)).await;
                                continue;
                            }
                        },
                        Err(e) => {
                            eprintln!("Failed to find sidecar ultron-backend: {}", e);
                            tokio::time::sleep(Duration::from_secs(2)).await;
                            continue;
                        }
                    };
                    
                    // Poll for readiness
                    let mut ready = false;
                    for _ in 0..60 { // wait up to 60 seconds
                        let client = reqwest::Client::new();
                        if let Ok(res) = client.get("http://127.0.0.1:8756/api/ready").send().await {
                            if res.status().is_success() {
                                println!("Backend is ready!");
                                ready = true;
                                break;
                            }
                        }
                        tokio::time::sleep(Duration::from_secs(1)).await;
                    }
                    
                    if !ready {
                        eprintln!("Backend failed to become ready within timeout.");
                        let _ = child.kill();
                    } else {
                        // Wait for process to exit
                        while let Some(event) = rx.recv().await {
                            if let CommandEvent::Terminated(payload) = event {
                                eprintln!("Backend terminated with payload: {:?}", payload);
                                break;
                            }
                        }
                    }
                    
                    println!("Backend process exited. Restarting...");
                    tokio::time::sleep(Duration::from_secs(2)).await;
                }
                
                eprintln!("Backend failed after {} attempts. Giving up.", max_attempts);
                std::process::exit(1);
            });
            
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running ULTRON desktop shell");
}
