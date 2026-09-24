import { useRef, useState } from 'react';

interface MutationOptions<T> {
  mutate: () => Promise<T>;
  onSuccess?: (value: T) => void;
  onError?: (error: unknown) => void;
}

export function useMutationWithRollback<T>({ mutate, onSuccess, onError }: MutationOptions<T>) {
  const inFlight = useRef(false);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const execute = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setIsPending(true);
    setError(null);
    try {
      const value = await mutate();
      onSuccess?.(value);
      return value;
    } catch (mutationError) {
      setError(mutationError);
      onError?.(mutationError);
      throw mutationError;
    } finally {
      inFlight.current = false;
      setIsPending(false);
    }
  };

  return { execute, isPending, error };
}
