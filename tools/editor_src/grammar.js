// The one list of markdown grammar extensions: the editor and the sync check both use it, so
// what the check verifies is exactly what the editor parses.
import { FrontMatterExt } from "./frontmatter.js";
import { TagExt } from "./tag.js";
import { MathExt } from "./math.js";
import { PageBreakExt } from "./pagebreak.js";
import { WikiLinkExt } from "./wikilink.js";

export const editorExtensions = [MathExt, FrontMatterExt, WikiLinkExt, TagExt, PageBreakExt];
