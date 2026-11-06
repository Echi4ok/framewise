import { describe, expect, it } from "vitest";
import { productDescriptionText } from "./productDescription";
import { formatUiText } from "./text";

describe("product description presentation", () => {
  it("renders paragraphs, breaks, inline HTML and decoded entities as text", () => {
    expect(
      productDescriptionText(
        "<p>Чемодан&nbsp;&amp;&nbsp;сумка</p><p>Размер <b>35</b> л<br>Серый</p>",
      ),
    ).toBe("Чемодан & сумка\n\nРазмер 35 л\nСерый");
    expect(productDescriptionText("&lt;b&gt; &quot;текст&quot; &#169;")).toBe(
      '<b> "текст" ©',
    );
  });

  it("omits script/style and other inert embedded content without executing it", () => {
    const before = document.body.innerHTML;
    const source =
      '<style>p { color: red }</style><script>document.body.innerHTML = "executed"</script><p>Описание</p><svg><script>document.body.innerHTML = "executed"</script><text>Hidden</text></svg><template>Template</template><iframe>Frame</iframe><img src="missing.jpg" onerror="document.body.innerHTML = \'executed\'">';
    expect(productDescriptionText(source)).toBe("Описание");
    expect(document.body.innerHTML).toBe(before);
  });

  it("preserves readable unordered and ordered lists", () => {
    expect(
      productDescriptionText(
        '<p>Детали</p><ul><li><b>Ручка</b></li><li><p>Замок</p></li><li><script>hidden</script></li></ul><ol start="3"><li>Первый шаг</li><li>Второй шаг</li></ol>',
      ),
    ).toBe("Детали\n\n• Ручка\n• Замок\n\n3. Первый шаг\n4. Второй шаг");
  });

  it("keeps plain-text line breaks and normalizes long dashes for display", () => {
    const source = "  Строка — первая\nСтроки 3–5  ";
    expect(productDescriptionText(source)).toBe("Строка - первая\nСтроки 3-5");
    expect(formatUiText("Товар — X – Y")).toBe("Товар - X - Y");
    expect(source).toContain("—");
  });
});
