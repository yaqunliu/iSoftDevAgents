import { Link } from "wouter";
import { useTranslation } from "react-i18next";
import { TerminalSquare, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui";

export default function NotFound() {
  const { t } = useTranslation();
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-background text-foreground">
      <div className="flex flex-col items-center max-w-md text-center p-8 border border-white/10 rounded-2xl bg-card shadow-2xl">
        <AlertCircle className="w-16 h-16 text-primary mb-6 opacity-80" />
        <h1 className="text-3xl font-bold mb-2">{t("notFound.title")}</h1>
        <p className="text-muted-foreground mb-8">
          {t("notFound.description")}
        </p>
        <Link href="/">
          <Button size="lg" className="w-full">
            <TerminalSquare className="w-4 h-4 mr-2" />
            {t("notFound.returnHome")}
          </Button>
        </Link>
      </div>
    </div>
  );
}
