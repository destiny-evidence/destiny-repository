import { render } from "preact";
import { App } from "./App";
import { initAuth } from "./auth/keycloak";
import PageOverlay from "./components/ui/PageOverlay";
import "./styles/globals.css";

const root = document.getElementById("app")!;

render(<PageOverlay message="Loading..." showSpinner={true} />, root);

initAuth()
  .then(() => render(<App />, root))
  .catch((err) => {
    console.error("Authentication initialization failed", err);
    render(
      <PageOverlay message="Unable to reach the sign-in service. Reload to try again." />,
      root,
    );
  });
