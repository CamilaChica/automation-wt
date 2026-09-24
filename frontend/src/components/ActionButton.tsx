import React, { useState } from 'react';

interface ActionButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  confirmation?: string;
  onAction: () => Promise<void> | void;
}

export const ActionButton: React.FC<ActionButtonProps> = ({ confirmation, onAction, children, disabled, ...props }) => {
  const [pending, setPending] = useState(false);

  const handleClick = async () => {
    if (confirmation && !window.confirm(confirmation)) return;
    if (pending) return;
    setPending(true);
    try {
      await onAction();
    } finally {
      setPending(false);
    }
  };

  return (
    <button {...props} type={props.type || 'button'} disabled={disabled || pending} aria-busy={pending} onClick={() => void handleClick()}>
      {pending ? 'Working...' : children}
    </button>
  );
};
