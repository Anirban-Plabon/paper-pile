// The one list of markdown grammar extensions: the editor and the sync check both use it, so
// what the check verifies is exactly what the editor parses.
import { FrontMatterExt } from "./frontmatter.js";
import { MathExt } from "./math.js";

export const editorExtensions = [MathExt, FrontMatterExt];
