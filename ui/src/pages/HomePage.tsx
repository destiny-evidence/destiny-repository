// Home page placeholder

export default function HomePage(_props: { path?: string }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "60vh",
        width: "100vw",
        marginLeft: "calc(-50vw + 50%)",
        background: "inherit",
        paddingLeft: 32,
        paddingRight: 32,
      }}
    >
      <h1
        style={{
          margin: "32px 0 24px 0",
          display: "block",
          width: "fit-content",
        }}
      >
        Welcome to DESTINY Repository
      </h1>
      <p style={{ fontSize: "1.2rem", color: "#122c91" }}>
        Select a page from the navigation bar to get started.
      </p>
    </div>
  );
}
