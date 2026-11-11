const Stub = ({ title, text }) => (
  <>
    <h1 className="page-title">{title}</h1>
    <p className="page-sub">{text}</p>
    <div className="stub">This screen is built in a later step.</div>
  </>
);

export const Subscriptions = () => <Stub title="Subscriptions" text="Every recurring payment, in one ledger." />;
export const Intelligence = () => <Stub title="AI Intelligence" text="Ask questions about your own saved subscriptions." />;
export const ImportCentre = () => <Stub title="Import" text="Bring subscriptions in from CSV files, PDFs, images or pasted emails." />;
export const Upgrade = () => <Stub title="Upgrade" text="Compare Free and Plus." />;
export const Notifications = () => <Stub title="Notifications" text="Renewal, trial and price alerts." />;
