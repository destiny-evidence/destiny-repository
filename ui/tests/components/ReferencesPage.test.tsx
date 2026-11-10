// End-to-end through the page with only the network and auth stubbed. These
// guard the React-to-Preact port: text inputs must update on each keystroke
// (onInput), not only on blur as Preact's native onChange would.

import { fireEvent, render, screen, waitFor } from "@testing-library/preact";
import ReferencesPage from "@/pages/ReferencesPage";

const auth = vi.hoisted(() => ({
  enabled: true,
  authenticated: true,
  username: "Ada",
  login: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("@/auth/AuthContext", () => ({
  useAuth: () => auth,
}));

vi.mock("@/auth/keycloak", () => ({
  getToken: async () => "tok",
}));

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status });
}

describe("ReferencesPage", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    auth.authenticated = true;
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("blocks the form when signed out", () => {
    auth.authenticated = false;
    render(<ReferencesPage />);

    expect(
      screen.getByText("This feature requires sign-in."),
    ).toBeInTheDocument();
  });

  it("looks up a reference by typed identifier", async () => {
    fetchMock.mockResolvedValue(
      respond(200, [
        {
          id: "02e376ee-8374-4a8c-997f-9a813bc5b8f8",
          identifiers: [{ identifier_type: "doi", identifier: "10.1/x" }],
          enhancements: [],
        },
      ]),
    );
    render(<ReferencesPage />);

    const lookup = screen.getByRole("button", { name: "Lookup Reference" });
    expect(lookup).toBeDisabled();

    fireEvent.input(screen.getAllByRole("textbox")[0], {
      target: { value: "10.1/x" },
    });
    expect(lookup).toBeEnabled();
    fireEvent.click(lookup);

    await waitFor(() =>
      expect(screen.getByText("Visual (1 reference)")).toBeInTheDocument(),
    );
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(
      "http://localhost:8000/v1/references/?identifier=doi%3A10.1%2Fx",
    );
    expect(init.headers.Authorization).toBe("Bearer tok");
  });

  it("counts bulk identifiers as they are typed", () => {
    render(<ReferencesPage />);

    fireEvent.input(screen.getByLabelText(/Enter identifiers/), {
      target: { value: "doi:10.1/x\n\npm_id:123" },
    });

    expect(
      screen.getByRole("button", { name: "Lookup 2 Identifiers" }),
    ).toBeEnabled();
  });

  it("searches and reports a query syntax error", async () => {
    fetchMock.mockResolvedValue(respond(400, { detail: "unbalanced quotes" }));
    render(<ReferencesPage />);

    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.input(screen.getByPlaceholderText("Enter search query..."), {
      target: { value: 'title:"oops' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search References" }));

    await waitFor(() =>
      expect(screen.getByText(/unbalanced quotes/)).toBeInTheDocument(),
    );
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://localhost:8000/v1/references/search/?q=title%3A%22oops&page=1",
    );
  });
});
