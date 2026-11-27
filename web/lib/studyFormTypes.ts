export type FieldType = "number" | "text" | "textarea" | "checkbox" | "date" | "select" | "multiselect";

export type FieldSpec = {
  key: string; // Google Sheets sütun başlığı
  label: string;
  type: FieldType;
  section: string;
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
};

export type FormSpec = {
  visits: string[]; // boşsa ziyaret seçimi yok (tek kayıt)
  computed: string[]; // sunucuda hesaplanıp yazılan sütunlar
  fields: FieldSpec[];
};
