import { toIdentifierString } from "@/api/identifierUtils";

describe("toIdentifierString", () => {
  it("prefixes supported identifier types", () => {
    expect(
      toIdentifierString({ identifier: "10.1234/abcd", identifierType: "doi" }),
    ).toBe("doi:10.1234/abcd");
  });

  it("leaves DESTINY IDs bare", () => {
    expect(
      toIdentifierString({
        identifier: "02e376ee-8374-4a8c-997f-9a813bc5b8f8",
        identifierType: "destiny_id",
      }),
    ).toBe("02e376ee-8374-4a8c-997f-9a813bc5b8f8");
  });

  it("includes the name of an other identifier", () => {
    expect(
      toIdentifierString({
        identifier: "978-1-234-56789-0",
        identifierType: "other",
        otherIdentifierName: "isbn",
      }),
    ).toBe("other:isbn:978-1-234-56789-0");
  });
});
