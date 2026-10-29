import { themeQuartz } from "ag-grid-community";

// Keyed to the same values as styles.css. The grid is the main surface here,
// so it has to sit inside the panel rather than look pasted onto it.
export const leashTheme = themeQuartz.withParams({
  accentColor: "#dfa33c",
  backgroundColor: "#0d0c0b",
  foregroundColor: "#ece7e1",
  borderColor: "#1e1a18",
  chromeBackgroundColor: "#121010",
  browserColorScheme: "dark",

  fontFamily: "Archivo, 'Segoe UI', system-ui, sans-serif",
  fontSize: "12.5px",

  headerBackgroundColor: "#121010",
  headerTextColor: "#6a635c",
  headerFontSize: "10px",
  headerFontWeight: 600,
  headerHeight: 32,

  rowHeight: 34,
  oddRowBackgroundColor: "#0d0c0b",
  rowHoverColor: "#171413",
  selectedRowBackgroundColor: "#211d17",
  rowBorder: { style: "solid", width: 1, color: "#171413" },

  wrapperBorder: false,
  wrapperBorderRadius: 0,
  borderRadius: 0,
  headerColumnBorder: false,
  cellHorizontalPadding: 12,

  inputBackgroundColor: "#0d0c0b",
  inputBorder: { color: "#2b2622" },
  inputTextColor: "#ece7e1",

  checkboxCheckedBackgroundColor: "#dfa33c",
  checkboxCheckedBorderColor: "#dfa33c",
  checkboxUncheckedBorderColor: "#3a342f",
  checkboxCheckedShapeColor: "#16120f",

  cellTextColor: "#ece7e1",
  columnBorder: false,
});
