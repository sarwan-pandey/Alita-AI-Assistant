/**
 * ChatLog — Animated conversation display with markdown rendering.
 * Features:
 *   - Framer Motion slide-in animations for each message
 *   - Markdown rendering (bold, code, lists) via react-markdown
 *   - Auto-scroll to latest message
 *   - Desktop notifications for assistant messages (when tab hidden)
 */

import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const messageVariants = {
  hidden: (role) => ({
    opacity: 0,
    x: role === "user" ? 40 : -40,
    y: 10,
    scale: 0.95,
  }),
  visible: {
    opacity: 1,
    x: 0,
    y: 0,
    scale: 1,
    transition: {
      type: "spring",
      stiffness: 300,
      damping: 25,
      duration: 0.4,
    },
  },
  exit: {
    opacity: 0,
    scale: 0.9,
    transition: { duration: 0.2 },
  },
};

export function ChatLog({ messages }) {
  const bottomRef = useRef(null);
  const containerRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Desktop notification for assistant messages when tab is hidden
  useEffect(() => {
    const last = messages[messages.length - 1];
    if (
      last?.role === "assistant" &&
      last?.final &&
      document.hidden &&
      "Notification" in window &&
      Notification.permission === "granted"
    ) {
      const text = last.content.slice(0, 100);
      new Notification("Aura says:", { body: text, icon: "/favicon.ico" });
    }
  }, [messages]);

  if (!messages.length) return null;

  return (
    <div className="chat-log" role="log" aria-live="polite" aria-label="Conversation" ref={containerRef}>
      <AnimatePresence mode="popLayout">
        {messages.map((msg) => (
          <motion.div
            key={msg.id}
            className={`chat-message ${msg.role}`}
            custom={msg.role}
            variants={messageVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            layout
          >
            <div className="chat-bubble">
              {msg.role === "assistant" ? (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    // Style code blocks (react-markdown v10: no `inline` prop)
                    code: ({ node, children, className, ...props }) => {
                      const isBlock = /language-/.test(className || '') ||
                        (node?.position?.start?.line !== node?.position?.end?.line);
                      return isBlock ? (
                        <pre className="code-block"><code className={className} {...props}>{children}</code></pre>
                      ) : (
                        <code className="inline-code" {...props}>{children}</code>
                      );
                    },
                    // Open links in new tab
                    a: ({ children, ...props }) => (
                      <a {...props} target="_blank" rel="noopener noreferrer">{children}</a>
                    ),
                  }}
                >
                  {msg.content}
                </ReactMarkdown>
              ) : (
                msg.content
              )}
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
      <div ref={bottomRef} />
    </div>
  );
}