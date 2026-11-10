import { fireEvent, render, screen } from "@testing-library/preact";
import AuthButton from "@/components/auth/AuthButton";

const auth = vi.hoisted(() => ({
  enabled: true,
  authenticated: false,
  username: undefined as string | undefined,
  login: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("@/auth/AuthContext", () => ({
  useAuth: () => auth,
}));

describe("AuthButton", () => {
  beforeEach(() => {
    auth.enabled = true;
    auth.authenticated = false;
    auth.username = undefined;
    auth.login.mockReset();
    auth.logout.mockReset();
  });

  it("offers sign-in when signed out", () => {
    render(<AuthButton />);

    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(auth.login).toHaveBeenCalled();
  });

  it("offers sign-out with the username when signed in", () => {
    auth.authenticated = true;
    auth.username = "Ada";
    render(<AuthButton />);

    fireEvent.click(screen.getByRole("button", { name: "Sign out (Ada)" }));

    expect(auth.logout).toHaveBeenCalled();
  });

  it("shows a static label when auth is disabled", () => {
    auth.enabled = false;
    render(<AuthButton />);

    expect(screen.getByText("Local Mode")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
