import { useCallback, useEffect, useMemo, useRef } from "react";
import { AgGridReact } from "ag-grid-react";
import type {
  ColDef,
  GridApi,
  GridReadyEvent,
  IRowNode,
  IsFullWidthRowParams,
  RowClassParams,
  RowHeightParams,
  SelectionChangedEvent,
  ValueGetterParams,
} from "ag-grid-community";
import { clockTime } from "../format";
import type { GridRow, LogRow } from "../types";
import { leashTheme } from "./theme";
import {
  EvidenceBand,
  HeadroomCell,
  MoneyCell,
  RulesCell,
  StateCell,
  VerdictCell,
  evidenceHeight,
  failuresOf,
  worstOf,
} from "./renderers";

const isDecision = (row: GridRow | undefined): row is LogRow =>
  row?.kind === "decision";

export interface DecisionGridProps {
  rows: GridRow[];
  expanded: Set<string>;
  onToggle: (attemptId: string) => void;
  onSelectionChange: (chargeIds: string[]) => void;
  onlyRefusals: boolean;
  query: string;
}

export function DecisionGrid({
  rows,
  expanded,
  onToggle,
  onSelectionChange,
  onlyRefusals,
  query,
}: DecisionGridProps) {
  const apiRef = useRef<GridApi<GridRow> | null>(null);

  const columnDefs = useMemo<ColDef<GridRow>[]>(
    () => [
      {
        headerName: "#",
        field: "sequence" as never,
        width: 72,
        minWidth: 72,
        cellClass: "num",
        sortable: true,
        valueGetter: (p: ValueGetterParams<GridRow>) =>
          isDecision(p.data) ? p.data.sequence : null,
      },
      {
        headerName: "TIME",
        width: 92,
        cellClass: "num",
        valueGetter: (p: ValueGetterParams<GridRow>) =>
          isDecision(p.data) ? clockTime(p.data.evaluated_at) : "",
      },
      {
        headerName: "VERDICT",
        width: 94,
        cellRenderer: VerdictCell,
        valueGetter: (p: ValueGetterParams<GridRow>) =>
          isDecision(p.data) ? p.data.verdict : "",
      },
      {
        headerName: "PAYEE",
        width: 124,
        valueGetter: (p: ValueGetterParams<GridRow>) =>
          isDecision(p.data) ? p.data.payee : "",
      },
      {
        headerName: "CATEGORY",
        width: 108,
        valueGetter: (p: ValueGetterParams<GridRow>) =>
          isDecision(p.data) ? p.data.category : "",
      },
      {
        headerName: "AMOUNT",
        width: 108,
        type: "rightAligned",
        cellRenderer: MoneyCell,
        valueGetter: (p: ValueGetterParams<GridRow>) =>
          isDecision(p.data) ? p.data.amount : null,
      },
      {
        headerName: "RULES THAT FIRED",
        flex: 1,
        minWidth: 240,
        sortable: false,
        cellRenderer: RulesCell,
        cellRendererParams: { expanded, onToggle },
        valueGetter: (p: ValueGetterParams<GridRow>) =>
          isDecision(p.data) ? p.data.failed_codes.join(" ") : "",
      },
      {
        headerName: "HEADROOM",
        width: 142,
        sortable: false,
        cellRenderer: HeadroomCell,
        valueGetter: (p: ValueGetterParams<GridRow>) =>
          isDecision(p.data) ? p.data.max_allowable : null,
      },
      {
        headerName: "MONEY",
        width: 104,
        sortable: true,
        cellRenderer: StateCell,
        // Flashes when a hold turns into a settled payout, so the moment the
        // money actually moves is visible rather than inferred.
        enableCellChangeFlash: true,
        valueGetter: (p: ValueGetterParams<GridRow>) =>
          isDecision(p.data) ? p.data.charge_state : null,
      },
    ],
    [expanded, onToggle],
  );

  const defaultColDef = useMemo<ColDef<GridRow>>(
    () => ({ resizable: true, sortable: false, suppressHeaderMenuButton: true }),
    [],
  );

  const getRowId = useCallback(
    ({ data }: { data: GridRow }) =>
      data.kind === "evidence" ? `e:${data.attempt_id}` : `d:${data.attempt_id}`,
    [],
  );

  const isFullWidthRow = useCallback(
    (p: IsFullWidthRowParams<GridRow>) => p.rowNode.data?.kind === "evidence",
    [],
  );

  const getRowHeight = useCallback((p: RowHeightParams<GridRow>) => {
    const row = p.data;
    if (row?.kind === "evidence") return evidenceHeight(row.parent);
    return 34;
  }, []);

  // Refusals carry a severity bar on the left edge. Allowed rows get nothing,
  // because a quiet row is the normal case and should read as unremarkable.
  const rowClassRules = useMemo(
    () => ({
      "row-blocked": (p: RowClassParams<GridRow>) =>
        isDecision(p.data) && p.data.verdict === "block",
      "row-critical": (p: RowClassParams<GridRow>) => {
        if (!isDecision(p.data)) return false;
        const fails = failuresOf(p.data);
        return fails.length > 0 && worstOf(fails) === "critical";
      },
      "row-high": (p: RowClassParams<GridRow>) => {
        if (!isDecision(p.data)) return false;
        const fails = failuresOf(p.data);
        return fails.length > 0 && worstOf(fails) === "high";
      },
      "row-settled": (p: RowClassParams<GridRow>) =>
        isDecision(p.data) && p.data.charge_state === "settled",
      "row-evidence": (p: RowClassParams<GridRow>) => p.data?.kind === "evidence",
    }),
    [],
  );

  const rowSelection = useMemo(
    () =>
      ({
        mode: "multiRow",
        checkboxes: true,
        headerCheckbox: true,
        enableClickSelection: false,
        hideDisabledCheckboxes: true,
        // Only a live hold can be paid out or handed back, so only a live hold
        // offers a checkbox. The grid says what is actionable.
        isRowSelectable: (node: IRowNode<GridRow>) =>
          isDecision(node.data) && node.data.charge_state === "pending",
      }) as never,
    [],
  );

  const onGridReady = useCallback((e: GridReadyEvent<GridRow>) => {
    apiRef.current = e.api;
  }, []);

  // The log is chronological, so new decisions land at the bottom. Follow them
  // down, otherwise a live run walks off the edge of the screen.
  const seen = useRef(0);
  useEffect(() => {
    const grid = apiRef.current;
    const count = rows.filter((r) => r.kind === "decision").length;
    if (grid && count > seen.current) {
      const last = grid.getDisplayedRowCount() - 1;
      if (last >= 0) grid.ensureIndexVisible(last, "bottom");
    }
    seen.current = count;
  }, [rows]);

  const onSelectionChanged = useCallback(
    (e: SelectionChangedEvent<GridRow>) => {
      const ids = e.api
        .getSelectedNodes()
        .map((n) => (isDecision(n.data) ? n.data.charge_id : null))
        .filter((id): id is string => Boolean(id));
      onSelectionChange(ids);
    },
    [onSelectionChange],
  );

  const isExternalFilterPresent = useCallback(() => onlyRefusals, [onlyRefusals]);

  const doesExternalFilterPass = useCallback((node: IRowNode<GridRow>) => {
    const row = node.data;
    if (!row) return true;
    if (row.kind === "evidence") return row.parent.verdict === "block";
    return row.verdict === "block";
  }, []);

  return (
    <div className="grid-host">
      <AgGridReact<GridRow>
        theme={leashTheme}
        rowData={rows}
        columnDefs={columnDefs}
        defaultColDef={defaultColDef}
        getRowId={getRowId}
        getRowHeight={getRowHeight}
        isFullWidthRow={isFullWidthRow}
        fullWidthCellRenderer={EvidenceBand}
        rowClassRules={rowClassRules}
        rowSelection={rowSelection}
        selectionColumnDef={{ width: 42, resizable: false } as never}
        onGridReady={onGridReady}
        onSelectionChanged={onSelectionChanged}
        isExternalFilterPresent={isExternalFilterPresent}
        doesExternalFilterPass={doesExternalFilterPass}
        quickFilterText={query}
        cellFlashDuration={1100}
        cellFadeDuration={500}
        animateRows
        suppressCellFocus={false}
        headerHeight={32}
        noRowsOverlayComponent={NoRows}
      />
    </div>
  );
}

function NoRows() {
  return (
    <div className="empty">
      <h3>Nothing has been asked for yet</h3>
      <p>
        Run the scenario, or send a single spend from the console below. Every
        decision lands here with the rules it was measured against.
      </p>
    </div>
  );
}
