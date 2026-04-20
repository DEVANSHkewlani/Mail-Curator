# Design System Document: High-End Editorial

## 1. Overview & Creative North Star

### Creative North Star: "The Digital Curator"
This design system moves away from the sterile, rigid grids of traditional SaaS and toward a high-end, editorial experience. It is designed to feel like a premium digital publication—intentional, sophisticated, and authoritative. By blending the classic elegance of **Instrument Serif** with the functional precision of **Inter**, we create a "Digital Curator" persona: an interface that doesn't just display data but presents it with narrative importance.

### Breaking the Template
We achieve a custom feel by embracing **intentional asymmetry** and **tonal depth**. Rather than using heavy lines to separate ideas, we use expansive white space and subtle shifts in warm background tones. Elements should feel "placed" rather than "slotted," using overlapping layers and varying card sizes to create a rhythmic, conversational flow across the layout.

---

## 2. Colors

The palette is anchored in a soft, warm cream (`background: #fbf9f4`) that reduces eye strain and provides a sophisticated alternative to pure white. The "soul" of the brand is expressed through **burnt orange accents** and **deep teal tertiary tones**.

### The "No-Line" Rule
**Explicit Instruction:** Designers are prohibited from using 1px solid borders for sectioning or containment. Traditional dividers are replaced by:
*   **Background Shifts:** Transitioning from `surface` (#fbf9f4) to `surface-container-low` (#f5f3ee).
*   **Vertical White Space:** Using the Spacing Scale to create clear mental breaks between content blocks.

### Surface Hierarchy & Nesting
Treat the UI as a physical stack of fine paper.
*   **Base:** `surface` (#fbf9f4)
*   **Sectioning:** `surface-container` (#f0eee9)
*   **Featured Cards:** `surface-container-lowest` (#ffffff) to provide a soft, natural "pop" against the warm background.

### The "Glass & Gradient" Rule
For floating elements like "Command Bars" or "Settings Overlays," use Glassmorphism. Utilize semi-transparent versions of `surface_container_lowest` with a `backdrop-blur` of 20px. 
*   **Signature Textures:** Main CTAs should use a subtle linear gradient from `primary` (#b02f00) to `primary_container` (#ff5722) at a 135-degree angle to add depth and a tactile quality.

---

## 3. Typography

The typographic pairing is the cornerstone of this system's "editorial" feel.

*   **Display & Headlines (Instrument Serif / Newsreader):** Used for large-scale storytelling and key data points. The high contrast of the serif letterforms communicates luxury and legacy.
    *   *Role:* Narrative headings, Hero statements, and prominent metrics (e.g., "18h Time Saved").
*   **Titles & Body (Inter):** A neutral, highly legible sans-serif that handles the heavy lifting of UI interaction and long-form data.
    *   *Role:* Navigation, labels, small body text, and functional UI elements.

**Hierarchy as Identity:** 
By setting small, all-caps Inter labels (`label-md`) above large Instrument Serif headlines (`display-md`), we create a sophisticated contrast typical of high-end fashion or architectural magazines.

---

## 4. Elevation & Depth

We reject the "drop shadow" defaults. Depth is achieved through **Tonal Layering**.

*   **The Layering Principle:** A card does not need a shadow to be seen. Place a `surface-container-lowest` card on a `surface-container-low` background. The subtle shift in hex code provides enough contrast for the eye to perceive a "lift."
*   **Ambient Shadows:** If a floating state is required (e.g., a modal), use a "Sunken Shadow": 
    *   *Blur:* 40px–60px.
    *   *Opacity:* 4%–6%.
    *   *Color:* Use `on-surface-variant` (#5b4039) instead of black to ensure the shadow feels like it belongs to the warm environment.
*   **The "Ghost Border":** For input fields or low-priority chips, use `outline-variant` (#e4beb4) at 20% opacity. It should be barely visible—a suggestion of a boundary, not a cage.

---

## 5. Components

### Buttons
*   **Primary:** Gradient fill (`primary` to `primary_container`), `9999px` (pill) radius, white text.
*   **Secondary:** Ghost-style. No fill, `outline` (#907067) at 30% opacity, `inter` medium weight text.
*   **Tertiary:** Text-only with a subtle `primary` underline on hover.

### Chips (Campaign Selectors)
*   Use `md` (0.75rem) roundedness.
*   **Active State:** 1px `primary` border with a very soft `primary-container` 10% opacity background tint.
*   **Inactive State:** `surface-container-high` background, no border.

### Cards & Lists
*   **Forbid Dividers:** Do not use lines between list items. Use 16px–24px of vertical padding to separate items.
*   **Nesting:** Place "Scanned Prospects" and "Verified Leads" metrics inside white cards (`surface-container-lowest`) with an `xl` (1.5rem) corner radius.

### Input Fields
*   **Command Bar:** A floating, high-radius pill (`9999px`) using `surface-container-lowest` and an Ambient Shadow.
*   **Text:** `Inter` body-md, 40% opacity for placeholders.

### Progress Indicators (The Flow Timeline)
*   Use a "soft-link" approach. Circular nodes connected by a low-contrast `outline-variant` line. Active nodes use a `primary` glow (8px blur).

---

## 6. Do's and Don'ts

### Do
*   **Do** use `Instrument Serif` for numbers in data visualizations to make metrics feel like "achievements."
*   **Do** lean into `xl` (1.5rem) corner radius for large containers to maintain the "Soft" aesthetic.
*   **Do** use asymmetrical layouts (e.g., a large card on the left, a slim timeline on the right) to avoid a "Bootstrap" feel.

### Don't
*   **Don't** use 100% black (#000000). Always use `on-background` (#1b1c19) for text to maintain the warm, organic palette.
*   **Don't** use sharp corners (`none` or `sm`). This system is built on "softened edges" to feel approachable and premium.
*   **Don't** use high-contrast borders. If the background colors are too similar to distinguish elements, increase the shift between surface tiers rather than adding a line.