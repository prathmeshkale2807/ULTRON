import React, { createContext, useContext, useState, useCallback } from 'react';
import { apiClient } from '../api/client';
import { usePolling } from '../hooks/usePolling';

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'tool' | 'system';
  content: string;
  metadata_json?: string | null;
  timestamp: string;
  tool_calls?: any[];
}

export interface Conversation {
  id: string;
  created_at: string;
  messages: Message[];
}

interface ConversationContextValue {
  activeConversation: Conversation | null;
  isLoading: boolean;
  sendMessage: (text: string, attachments?: { data_base64: string, mime_type: string }[]) => Promise<void>;
}

const ConversationContext = createContext<ConversationContextValue | undefined>(undefined);

export function ConversationProvider({ children }: { children: React.ReactNode }) {
  const [activeConversation, setActiveConversation] = useState<Conversation | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const fetchConversation = useCallback(async () => {
    // If no active conversation, fetch the recent one or create one
    try {
      if (activeConversation) {
        const data = await apiClient<Conversation>(`/api/conversations/${activeConversation.id}`);
        setActiveConversation(data);
      }
    } catch (err) {
      console.error('Failed to sync conversation', err);
    }
  }, [activeConversation]);

  usePolling(fetchConversation, 3000, !!activeConversation);

  const sendMessage = async (text: string, attachments?: { data_base64: string, mime_type: string }[]) => {
    if (!text.trim() && (!attachments || attachments.length === 0)) return;
    setIsLoading(true);
    try {
      let convId = activeConversation?.id;
      if (!convId) {
        convId = crypto.randomUUID();
      }
      
      const payload: any = { content: text };
      if (attachments && attachments.length > 0) {
        payload.metadata = { attachments };
      }
      
      await apiClient(`/api/conversations/${convId}/messages`, {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      
      // Force a fetch right away
      const updated = await apiClient<Conversation>(`/api/conversations/${convId}`);
      setActiveConversation(updated);
    } catch (err) {
      console.error('Failed to send message', err);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <ConversationContext.Provider value={{ activeConversation, isLoading, sendMessage }}>
      {children}
    </ConversationContext.Provider>
  );
}

export function useConversation() {
  const ctx = useContext(ConversationContext);
  if (!ctx) throw new Error('useConversation must be used within ConversationProvider');
  return ctx;
}
