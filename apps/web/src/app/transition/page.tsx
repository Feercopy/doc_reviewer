import Link from "next/link";

export default function TransitionPage() {
  return (
    <main className="transition-page">
      <div className="transition-content">
        <div className="transition-brand">Gate Challenger</div>
        <h1>По соображениям безопасности Gate Challenger переезжает во внутренний контур Авито.</h1>
        <p>Все новые анализы можно делать через скиллсет в Skill Hub - gate-challenger-skillset.</p>
        <p>
          <a href="https://cf.avito.ru/x/GDFIOw">Инструкция по установке и использованию</a>
          {" - доступно только из внутренней сети."}
        </p>
        <p>В ближайшее время визуальный интерфейс Gate Challenger появится внутри контура Авито.</p>
        <p>Все вопросы можно задать в личных сообщениях Маттермост vssyrov</p>
        <Link className="transition-admin-link" href="/login">Вход для администратора</Link>
      </div>
    </main>
  );
}
