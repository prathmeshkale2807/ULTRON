import React from 'react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { SafetyProvider } from './contexts/SafetyContext';
import { ConversationProvider } from './contexts/ConversationContext';
import { ErrorBoundary } from './components/ErrorBoundary';
import { MainLayout } from './layout/MainLayout';

// Views
import { JarvisView } from './views/JarvisView';
import { ChatView } from './views/ChatView';
import { SecurityView } from './views/SecurityView';
import { TasksView } from './views/TasksView';
import { DevicesView } from './views/DevicesView';

export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <SafetyProvider>
          <ConversationProvider>
            {/* Using MemoryRouter since this is a desktop app (Tauri doesn't have a real URL bar) */}
            <MemoryRouter>
              <Routes>
                <Route path="/" element={<MainLayout />}>
                  <Route index element={<JarvisView />} />
                  <Route path="chat" element={<ChatView />} />
                  <Route path="devices" element={<DevicesView />} />
                  <Route path="tasks" element={<TasksView />} />
                  <Route path="security" element={<SecurityView />} />
                </Route>
              </Routes>
            </MemoryRouter>
          </ConversationProvider>
        </SafetyProvider>
      </AuthProvider>
    </ErrorBoundary>
  );
}

