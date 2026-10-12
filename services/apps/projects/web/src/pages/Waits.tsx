import { useEffect, useState } from "react";
import { api, type Item } from "../api";
import { ItemList } from "../items";
import { Card, ErrorBox, Skeleton } from "../ui";

export default function Waits() {
  const [todos, setTodos] = useState<Item[] | null>(null);
  const [error, setError] = useState("");
  const load = () => api.userTodos().then(setTodos).catch((e) => setError(String(e)));
  useEffect(() => { load(); }, []);
  if (error) return <ErrorBox error={error} />;
  if (!todos) return <Skeleton />;
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Ждёт тебя</h1>
        <p className="mt-1 text-sm text-muted">То, что могу сделать только ты: одобрить, зарегистрировать, оплатить, нажать.</p>
      </header>
      <Card className="py-2"><ItemList items={todos} onChange={load} withProject empty="Ничего не ждёт." /></Card>
    </div>
  );
}
