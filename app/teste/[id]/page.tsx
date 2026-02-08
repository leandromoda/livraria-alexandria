export default function Teste({ params }: any) {
  return (
    <div style={{ padding: 40 }}>
      ID: {params?.id}
    </div>
  );
}
