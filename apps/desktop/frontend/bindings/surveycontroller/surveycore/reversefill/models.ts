

export interface Answer {
    "question_num": number;
    "kind": string;
    "choice_index"?: number | null;
    "text_value"?: string;
    "text_values"?: string[] | null;
    "matrix_choice_indexes"?: number[] | null;
}

export interface Column {
    "column_index": number;
    "header": string;
    "question_num": number;
    "suffix"?: string;
}

export interface Preview {
    "source_path": string;
    "selected_format": string;
    "detected_format": string;
    "header_row_number": number;
    "total_data_rows": number;
    "question_columns": { [_ in `${number}`]?: Column[] | null } | null;
    "sample_rows": SampleRow[] | null;
    "unsupported_fields"?: string[] | null;
}

export interface SampleRow {
    "data_row_number": number;
    "worksheet_row_number": number;
    "answers": { [_ in `${number}`]?: Answer } | null;
}
