import { apiGet } from "@/api/client";

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status });
}

describe("apiGet", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("joins the path onto the API base and returns the body", async () => {
    fetchMock.mockResolvedValue(respond(200, [{ id: "a" }]));

    const result = await apiGet("/references/?identifier=doi:1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/v1/references/?identifier=doi:1",
      { headers: {} },
    );
    expect(result).toEqual({ data: [{ id: "a" }], error: null });
  });

  it("sends the token as a bearer header", async () => {
    fetchMock.mockResolvedValue(respond(200, []));

    await apiGet("/references/", "tok");

    expect(fetchMock.mock.calls[0][1]).toEqual({
      headers: { Authorization: "Bearer tok" },
    });
  });

  it.each([400, 422])("reports %i as a validation error", async (status) => {
    fetchMock.mockResolvedValue(respond(status, { detail: "bad query" }));

    expect(await apiGet("/references/search/")).toEqual({
      data: null,
      error: { type: "validation", detail: "bad query" },
    });
  });

  it("stringifies structured validation detail", async () => {
    const detail = [{ loc: ["query", "q"], msg: "Field required" }];
    fetchMock.mockResolvedValue(respond(422, { detail }));

    const result = await apiGet("/references/search/");

    expect(result.error).toEqual({
      type: "validation",
      detail: JSON.stringify(detail),
    });
  });

  it("reports other failures as generic errors", async () => {
    fetchMock.mockResolvedValue(respond(401, { detail: "Not authenticated" }));

    expect(await apiGet("/references/")).toEqual({
      data: null,
      error: { type: "generic", detail: "Not authenticated" },
    });
  });

  it("survives a non-JSON error body", async () => {
    fetchMock.mockResolvedValue(new Response("<html>", { status: 502 }));

    expect((await apiGet("/references/")).error).toEqual({
      type: "generic",
      detail: "API error",
    });
  });

  it("reports a network failure as a generic error", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    expect((await apiGet("/references/")).error).toEqual({
      type: "generic",
      detail: "API error",
    });
  });
});
