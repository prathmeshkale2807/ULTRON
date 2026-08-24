import React, { useState, useRef, useEffect } from 'react';
import { useConversation, Message } from '../contexts/ConversationContext';
import { Send, Paperclip, X } from 'lucide-react';
import { apiClient } from '../api/client';

function AttachmentImage({ attachmentId }: { attachmentId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let objectUrl: string;
    apiClient<Blob>(`/api/attachments/${attachmentId}`, { 
      responseType: 'blob' 
    } as any)
      .then(blob => {
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => setError(true));
      
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [attachmentId]);

  if (error) return <div style={{ color: 'red', fontSize: '0.8rem' }}>Failed to load image</div>;
  if (!url) return <div style={{ fontSize: '0.8rem' }}>Loading image...</div>;

  return <img src={url} alt="attachment" style={{ maxWidth: '200px', maxHeight: '200px', borderRadius: '8px' }} />;
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user';
  
  // Parse attachments from metadata if present
  let attachments: any[] = [];
  if (msg.metadata_json) {
    try {
      const meta = JSON.parse(msg.metadata_json);
      if (meta.attachments) {
        attachments = meta.attachments;
      }
    } catch (e) {}
  }

  return (
    <div style={{
      display: 'flex',
      justifyContent: isUser ? 'flex-end' : 'flex-start',
      marginBottom: '1rem'
    }}>
      <div style={{
        background: isUser ? 'var(--color-primary)' : 'var(--color-bg-card)',
        color: isUser ? 'white' : 'var(--color-text-main)',
        padding: '0.75rem 1rem',
        borderRadius: '12px',
        border: isUser ? 'none' : '1px solid var(--color-border)',
        maxWidth: '80%',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word'
      }}>
        {/* Render attachments safely using authenticated API endpoint */}
        {attachments.length > 0 && (
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
            {attachments.map((att, idx) => (
              <AttachmentImage key={idx} attachmentId={att.attachment_id} />
            ))}
          </div>
        )}
        
        {msg.content}
        
        {msg.tool_calls && msg.tool_calls.length > 0 && (
          <div style={{ marginTop: '0.5rem', padding: '0.5rem', background: 'rgba(0,0,0,0.2)', borderRadius: '4px', fontSize: '0.85rem' }}>
            <em>Tool Calls:</em>
            <pre style={{ margin: 0, overflowX: 'auto' }}>
              {JSON.stringify(msg.tool_calls, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

export function ChatView() {
  const { activeConversation, isLoading, sendMessage } = useConversation();
  const [input, setInput] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0];
      setSelectedFile(file);
      setPreviewUrl(URL.createObjectURL(file));
    }
  };

  const clearFile = () => {
    setSelectedFile(null);
    setPreviewUrl(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const fileToBase64 = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = () => {
        const result = reader.result as string;
        // Strip the data:image/png;base64, prefix
        resolve(result.split(',')[1]);
      };
      reader.onerror = error => reject(error);
    });
  };

  const handleSend = async () => {
    if (!input.trim() && !selectedFile) return;
    
    let attachments: { data_base64: string, mime_type: string }[] | undefined;
    if (selectedFile) {
      const b64 = await fileToBase64(selectedFile);
      attachments = [{ data_base64: b64, mime_type: selectedFile.type }];
    }
    
    const textToSend = input;
    setInput('');
    clearFile();
    
    sendMessage(textToSend, attachments);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ flex: 1, overflowY: 'auto', padding: '1rem', border: '1px solid var(--color-border)', borderRadius: '8px', marginBottom: '1rem', background: '#0f111a' }}>
        {!activeConversation || activeConversation.messages.length === 0 ? (
          <div style={{ color: 'var(--color-text-sub)', textAlign: 'center', marginTop: '2rem' }}>
            No active conversation. Type a message to start.
          </div>
        ) : (
          activeConversation.messages.map((msg, i) => (
            <MessageBubble key={msg.id || i} msg={msg} />
          ))
        )}
      </div>
      
      {previewUrl && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem', padding: '0.5rem', background: 'var(--color-bg-card)', borderRadius: '8px' }}>
          <img src={previewUrl} alt="Preview" style={{ height: '60px', borderRadius: '4px' }} />
          <button className="btn" style={{ background: 'transparent', padding: '4px' }} onClick={clearFile}>
            <X size={16} />
          </button>
        </div>
      )}
      
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <input 
          type="file" 
          accept="image/jpeg, image/png, image/webp" 
          style={{ display: 'none' }} 
          ref={fileInputRef}
          onChange={handleFileChange}
        />
        <button 
          className="btn" 
          onClick={() => fileInputRef.current?.click()} 
          disabled={isLoading}
          style={{ background: 'var(--color-bg-card)' }}
        >
          <Paperclip size={18} />
        </button>
        <input 
          type="text" 
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Ask ULTRON..."
          disabled={isLoading}
          style={{ flex: 1, padding: '0.75rem', borderRadius: '8px', border: '1px solid var(--color-border)', background: 'var(--color-bg-card)', color: 'white' }}
        />
        <button className="btn" onClick={handleSend} disabled={isLoading || (!input.trim() && !selectedFile)}>
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}
