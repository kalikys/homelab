import { useEffect, useState } from "react";
import { api, type Item } from "../api";
import { ItemList } from "../items";
import { Empty } from "../ui";

export default function Waits() {
  const [todos, setTodos] = useState<Item[] | null>(null);
  const load = () => api.userTodos().then(setTodos);
  useEffect(() => { load(); }, []);
  if (!todos) return <Empty>Загрузка…</Empty>;
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">Ждёт тебя</h1>
      <ItemList items={todos} onChange={load} withProject empty="Ничего не ждёт." />
    </div>
  );
}
